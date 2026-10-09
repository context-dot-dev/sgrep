mod codechunker;
mod splitter;

use clap::{Parser, ValueEnum};
use half::f16;
use rayon::prelude::*;
use regex::Regex;
use serde::Serialize;
use std::collections::{HashMap, HashSet};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::sync::LazyLock;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;
struct Model {
    repo: &'static str,
    revision: &'static str,
    rows: usize,
    dtype: safetensors::Dtype,
}
const CODE: Model = Model {
    repo: "minishlab/potion-code-16M-v2",
    revision: "e9d2a44ca6a05ac6685f3b23709ea57eb7352d5b",
    rows: 63457,
    dtype: safetensors::Dtype::F16,
};
const TEXT: Model = Model {
    repo: "minishlab/potion-base-8M",
    revision: "bf8b056651a2c21b8d2565580b8569da283cab23",
    rows: 29528,
    dtype: safetensors::Dtype::F32,
};

#[derive(Clone, Copy, PartialEq, ValueEnum)]
enum ModelChoice {
    Auto,
    Code,
    Text,
}
static CAMEL: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"([a-z0-9])([A-Z])").unwrap());
static WORD: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"[\p{L}\p{N}]+").unwrap());
static STOP: LazyLock<HashSet<&str>> = LazyLock::new(|| {
    "a an and are as at be been but by can do does for from had has have how i if in into is it its me not of on or our should so that the their them there these they this to use using was we what when where which who will with would you your function description purpose input output".split_whitespace().collect()
});

#[derive(Parser)]
#[command(
    version,
    about = "Search code and text with ripgrep and local static embeddings."
)]
struct Args {
    query: String,
    #[arg(default_value = ".")]
    path: PathBuf,
    #[arg(short = 'n', default_value_t = 5, value_parser = clap::value_parser!(u32).range(1..))]
    count: u32,
    #[arg(long)]
    json: bool,
    /// Auto uses text embeddings for prose-only candidates, code embeddings otherwise.
    #[arg(long, value_enum, default_value_t = ModelChoice::Auto)]
    model: ModelChoice,
}

#[derive(Serialize)]
struct Chunk {
    path: String,
    start: usize,
    end: usize,
    content: String,
    #[serde(skip)]
    counts: HashMap<String, usize>,
}

fn words(text: &str) -> Vec<String> {
    let text = CAMEL.replace_all(text, "${1} ${2}").to_lowercase();
    WORD.find_iter(&text)
        .map(|m| m.as_str())
        .filter(|w| w.chars().count() > 1 && !STOP.contains(w))
        .map(str::to_owned)
        .collect()
}

fn filename(bytes: &[u8]) -> PathBuf {
    #[cfg(unix)]
    {
        use std::os::unix::ffi::OsStrExt;
        std::ffi::OsStr::from_bytes(bytes).into()
    }
    #[cfg(not(unix))]
    {
        String::from_utf8_lossy(bytes).as_ref().into()
    }
}

fn candidates(path: &Path, terms: &[String]) -> Result<Vec<Chunk>> {
    let root = if path.is_dir() {
        path
    } else {
        path.parent().unwrap()
    };
    let mut command = Command::new("rg");
    command.args(["--no-config", "-l", "-0", "-i", "-F"]);
    for term in terms {
        command.args(["-e", term]);
    }
    let target = if path.is_dir() {
        Path::new(".")
    } else {
        Path::new(path.file_name().unwrap())
    };
    let result = command
        .arg("--")
        .arg(target)
        .current_dir(root)
        .output()
        .map_err(|e| format!("ripgrep is required: {e}"))?;
    if !matches!(result.status.code(), Some(0 | 1)) {
        return Err(String::from_utf8_lossy(&result.stderr).into_owned().into());
    }
    let terms: HashSet<&str> = terms.iter().map(String::as_str).collect();
    let mut files: Vec<_> = result
        .stdout
        .split(|b| *b == 0)
        .filter(|b| !b.is_empty())
        .collect();
    files.sort_unstable();
    let chunks: Result<Vec<Vec<Chunk>>> = files
        .par_iter()
        .map(|name| {
            let mut chunks = Vec::new();
            let relative = filename(name);
            let relative = relative.strip_prefix(".").unwrap_or(&relative);
            let file = root.join(relative);
            let bytes = std::fs::read(&file)?;
            let source = String::from_utf8_lossy(&bytes)
                .replace("\r\n", "\n")
                .replace('\r', "\n");
            let lines: Vec<&str> = source.split_inclusive('\n').collect();
            let path_words = words(&relative.to_string_lossy());
            for (first, last) in splitter::ranges(&source, relative)? {
                let content = lines[first - 1..last].concat();
                let mut counts = HashMap::new();
                for word in words(&content) {
                    *counts.entry(word).or_insert(0) += 1;
                }
                if terms.iter().any(|t| counts.contains_key(*t)) {
                    for word in &path_words {
                        *counts.entry(word.clone()).or_insert(0) += 1;
                    }
                    chunks.push(Chunk {
                        path: relative.to_string_lossy().into_owned(),
                        start: first,
                        end: last,
                        content,
                        counts,
                    });
                }
            }
            Ok(chunks)
        })
        .collect();
    Ok(chunks?.into_iter().flatten().collect())
}

fn bm25(chunks: &[Chunk], terms: &[String]) -> Vec<usize> {
    let lengths: Vec<usize> = chunks.iter().map(|c| c.counts.values().sum()).collect();
    let average = lengths.iter().sum::<usize>() as f64 / chunks.len() as f64;
    let idfs: Vec<_> = terms
        .iter()
        .map(|t| {
            let df = chunks.iter().filter(|c| c.counts.contains_key(t)).count() as f64;
            (1.0 + (chunks.len() as f64 - df + 0.5) / (df + 0.5)).ln()
        })
        .collect();
    let scores: Vec<f64> = chunks
        .iter()
        .zip(lengths)
        .map(|(c, length)| {
            terms
                .iter()
                .zip(&idfs)
                .filter_map(|(t, idf)| {
                    c.counts.get(t).map(|count| {
                        let count = *count as f64;
                        idf * count * 2.5 / (count + 1.5 * (0.25 + 0.75 * length as f64 / average))
                    })
                })
                .sum()
        })
        .collect();
    let mut order: Vec<_> = (0..chunks.len()).collect();
    order.sort_by(|&a, &b| scores[b].total_cmp(&scores[a]));
    order.truncate(200);
    order
}

fn model_file(model: &Model, name: &str) -> Result<PathBuf> {
    let cache = std::env::var_os("HF_HUB_CACHE")
        .or_else(|| std::env::var_os("HUGGINGFACE_HUB_CACHE"))
        .map(PathBuf::from)
        .unwrap_or_else(|| hf_hub::Cache::from_env().path().clone());
    let file = cache
        .join(format!("models--{}", model.repo.replace('/', "--")))
        .join("snapshots")
        .join(model.revision)
        .join(name);
    if file.is_file() {
        return Ok(file);
    }
    if matches!(
        std::env::var("HF_HUB_OFFLINE")
            .unwrap_or_default()
            .to_uppercase()
            .as_str(),
        "1" | "TRUE" | "YES" | "ON"
    ) {
        return Err(format!(
            "{} {name} is not cached; run once online to download it",
            model.repo
        )
        .into());
    }
    let api = hf_hub::api::sync::ApiBuilder::from_env()
        .with_cache_dir(cache)
        .with_progress(false)
        .build()?;
    Ok(api
        .repo(hf_hub::Repo::with_revision(
            model.repo.into(),
            hf_hub::RepoType::Model,
            model.revision.into(),
        ))
        .get(name)?)
}

fn embed(texts: Vec<String>, model: &Model) -> Result<Vec<Vec<f32>>> {
    let tokenizer = tokenizers::Tokenizer::from_file(model_file(model, "tokenizer.json")?)?;
    let file = std::fs::read(model_file(model, "model.safetensors")?)?;
    let tensors = safetensors::SafeTensors::deserialize(&file)?;
    let tensor = tensors.tensor("embeddings")?;
    if tensor.dtype() != model.dtype || tensor.shape() != [model.rows, 256] {
        return Err("unexpected model tensor".into());
    }
    let weights: Vec<f32> = match model.dtype {
        safetensors::Dtype::F16 => tensor
            .data()
            .chunks_exact(2)
            .map(|b| f16::from_le_bytes([b[0], b[1]]).to_f32())
            .collect(),
        safetensors::Dtype::F32 => tensor
            .data()
            .chunks_exact(4)
            .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
            .collect(),
        _ => return Err("unsupported model dtype".into()),
    };
    let unknown = tokenizer.token_to_id("[UNK]");
    let encoded = tokenizer.encode_batch_fast(texts, false)?;
    let mut vectors = Vec::new();
    for encoding in encoded {
        let mut vector = vec![0.0f32; 256];
        let ids: Vec<_> = encoding
            .get_ids()
            .iter()
            .filter(|&&id| Some(id) != unknown)
            .collect();
        for &&id in &ids {
            let offset = id as usize * 256;
            for (x, weight) in vector.iter_mut().zip(&weights[offset..offset + 256]) {
                *x += weight;
            }
        }
        if !ids.is_empty() {
            for x in &mut vector {
                *x /= ids.len() as f32;
            }
        }
        let norm = vector.iter().map(|x| x * x).sum::<f32>().sqrt() + 1e-32;
        for x in &mut vector {
            *x /= norm;
        }
        if !vector.iter().all(|x| x.is_finite()) {
            return Err("non-finite embedding".into());
        }
        vectors.push(vector);
    }
    Ok(vectors)
}

fn search(args: &Args) -> Result<Vec<Chunk>> {
    let mut terms = words(&args.query);
    terms.sort();
    terms.dedup();
    if terms.is_empty() {
        return Err("query has no searchable words".into());
    }
    let path = args.path.canonicalize()?;
    if !path.is_file() && !path.is_dir() {
        return Err("not a file or directory".into());
    }
    let chunks = candidates(&path, &terms)?;
    if chunks.is_empty() {
        return Ok(Vec::new());
    }
    let order = bm25(&chunks, &terms);
    let mut texts = vec![args.query.clone()];
    texts.extend(order.iter().map(|&i| {
        format!(
            "{}\n{}",
            Path::new(&chunks[i].path)
                .file_name()
                .unwrap()
                .to_string_lossy(),
            chunks[i].content
        )
    }));
    let prose_only = order.iter().all(|&i| {
        let extension = Path::new(&chunks[i].path)
            .extension()
            .unwrap_or_default()
            .to_string_lossy()
            .to_ascii_lowercase();
        matches!(
            extension.as_str(),
            "md" | "mdx" | "txt" | "rst" | "adoc" | "org" | "text"
        )
    });
    let model =
        if args.model == ModelChoice::Text || (args.model == ModelChoice::Auto && prose_only) {
            &TEXT
        } else {
            &CODE
        };
    let vectors = embed(texts, model)?;
    let scores: Vec<f32> = vectors[1..]
        .iter()
        .map(|v| v.iter().zip(&vectors[0]).map(|(a, b)| a * b).sum())
        .collect();
    let mut semantic: Vec<_> = (0..order.len()).collect();
    semantic.sort_by(|&a, &b| scores[b].total_cmp(&scores[a]));
    let mut ranks = vec![0; order.len()];
    for (rank, &i) in semantic.iter().enumerate() {
        ranks[i] = rank;
    }
    let mut fused: Vec<_> = (0..order.len()).collect();
    let score = |i: usize| 1.0 / (61 + i) as f64 + 1.0 / (61 + ranks[i]) as f64;
    fused.sort_by(|&a, &b| score(b).total_cmp(&score(a)));
    let mut chunks: Vec<_> = chunks.into_iter().map(Some).collect();
    let mut results: Vec<Chunk> = Vec::new();
    for i in fused {
        let chunk = chunks[order[i]].take().unwrap();
        if results
            .iter()
            .any(|c| c.path == chunk.path && c.start <= chunk.end && chunk.start <= c.end)
        {
            continue;
        }
        results.push(chunk);
        if results.len() == args.count as usize {
            break;
        }
    }
    Ok(results)
}

fn run() -> Result<ExitCode> {
    let args = Args::parse();
    let results = search(&args)?;
    let mut out = io::BufWriter::new(io::stdout().lock());
    if args.json {
        writeln!(out, "{}", serde_json::to_string(&results)?)?;
    } else {
        for c in &results {
            writeln!(
                out,
                "{}:{}-{}\n{}\n",
                c.path,
                c.start,
                c.end,
                c.content.trim_end()
            )?;
        }
    }
    out.flush()?;
    Ok(ExitCode::from(if results.is_empty() { 1 } else { 0 }))
}

fn main() -> ExitCode {
    match run() {
        Ok(code) => code,
        Err(e) => {
            if e.downcast_ref::<io::Error>()
                .is_some_and(|e| e.kind() == io::ErrorKind::BrokenPipe)
            {
                return ExitCode::SUCCESS;
            }
            eprintln!("sgrep: {e}");
            ExitCode::from(2)
        }
    }
}
