mod codechunker;
mod embedding_cache;
mod rg_input;
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
    /// Add ripgrep --json matches and context from a file, or - for stdin.
    #[arg(long, value_name = "FILE")]
    rg_json: Option<PathBuf>,
    /// Rank only ripgrep --json passages read from standard input.
    #[arg(long, conflicts_with = "rg_json")]
    stdin: bool,
    /// Compute fresh corpus embeddings without reading or writing the cache.
    #[arg(long)]
    no_cache: bool,
    /// Include lexical, semantic and fused scores in JSON output.
    #[arg(long, requires = "json")]
    explain: bool,
}

#[derive(Serialize)]
struct Chunk {
    path: String,
    start: usize,
    end: usize,
    content: String,
    #[serde(skip)]
    counts: HashMap<String, usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    scores: Option<Scores>,
}

#[derive(Serialize)]
struct Scores {
    bm25: f64,
    semantic: f64,
    bm25_relative: f64,
    semantic_relative: f64,
    fused: f64,
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

fn candidates(path: &Path) -> Result<Vec<Chunk>> {
    let root = if path.is_dir() {
        path
    } else {
        path.parent().unwrap()
    };
    let mut command = Command::new("rg");
    command.args(["--no-config", "--files", "-0"]);
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
            if bytes.contains(&0) {
                return Ok(chunks);
            }
            let source = String::from_utf8_lossy(&bytes)
                .replace("\r\n", "\n")
                .replace('\r', "\n");
            let lines: Vec<&str> = source.split_inclusive('\n').collect();
            for (first, last) in splitter::ranges(&source, relative)? {
                chunks.push(make_chunk(
                    relative.to_string_lossy().into_owned(),
                    first,
                    last,
                    lines[first - 1..last].concat(),
                ));
            }
            Ok(chunks)
        })
        .collect();
    Ok(chunks?.into_iter().flatten().collect())
}

fn make_chunk(path: String, start: usize, end: usize, content: String) -> Chunk {
    let mut counts = HashMap::new();
    for word in words(&content).into_iter().chain(words(&path)) {
        *counts.entry(word).or_insert(0) += 1;
    }
    Chunk {
        path,
        start,
        end,
        content,
        counts,
        scores: None,
    }
}

fn bm25(chunks: &[Chunk], terms: &[String], corpus_len: usize) -> Vec<f64> {
    let lengths: Vec<usize> = chunks.iter().map(|c| c.counts.values().sum()).collect();
    let average =
        (lengths[..corpus_len].iter().sum::<usize>() as f64 / corpus_len.max(1) as f64).max(1.0);
    let idfs: Vec<_> = terms
        .iter()
        .map(|t| {
            let df = chunks[..corpus_len]
                .iter()
                .filter(|c| c.counts.contains_key(t))
                .count() as f64;
            (1.0 + (corpus_len as f64 - df + 0.5) / (df + 0.5)).ln()
        })
        .collect();
    chunks
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
        .collect()
}

fn relative_scores(scores: &[f64]) -> Vec<f64> {
    let min = scores.iter().copied().fold(f64::INFINITY, f64::min);
    let max = scores.iter().copied().fold(f64::NEG_INFINITY, f64::max);
    scores
        .iter()
        .map(|s| {
            if max > min {
                (s - min) / (max - min)
            } else {
                0.0
            }
        })
        .collect()
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
    let mut tokenizer = tokenizers::Tokenizer::from_file(model_file(model, "tokenizer.json")?)?;
    tokenizer.with_truncation(None)?;
    tokenizer.with_padding(None);
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
    encoded
        .par_iter()
        .map(|encoding| {
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
            Ok(vector)
        })
        .collect()
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
    let mut chunks = if args.stdin {
        rg_input::read(Path::new("-"), &path)?
    } else {
        candidates(&path)?
    };
    let mut seen = HashSet::new();
    chunks.retain(|c| seen.insert((c.path.clone(), c.start, c.end)));
    let corpus_len = chunks.len();
    let mut supplied = Vec::new();
    if let Some(input) = &args.rg_json {
        let mut locations: HashMap<_, _> = chunks
            .iter()
            .enumerate()
            .map(|(i, c)| ((c.path.clone(), c.start, c.end), i))
            .collect();
        for chunk in rg_input::read(input, &path)? {
            let key = (chunk.path.clone(), chunk.start, chunk.end);
            let i = *locations.entry(key).or_insert_with(|| {
                let i = chunks.len();
                chunks.push(chunk);
                i
            });
            supplied.push(i);
        }
    }
    if chunks.is_empty() {
        return Ok(Vec::new());
    }
    let lexical = bm25(&chunks, &terms, corpus_len);
    let prose_only = chunks.iter().all(|chunk| {
        let extension = Path::new(&chunk.path)
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
    let query_vector = embed(vec![args.query.clone()], model)?.remove(0);
    let texts = chunks
        .iter()
        .map(|c| format!("{}\n{}", c.path, c.content))
        .collect();
    let vectors = embedding_cache::corpus(
        texts,
        model,
        &path,
        args.no_cache || args.stdin || args.rg_json.is_some(),
    )?;
    let similarities: Vec<f64> = vectors
        .iter()
        .map(|v| v.iter().zip(&query_vector).map(|(a, b)| a * b).sum::<f32>() as f64)
        .collect();
    let mut order: Vec<_> = if args.stdin {
        (0..chunks.len()).collect()
    } else {
        let mut lexical_order: Vec<_> = (0..corpus_len).filter(|&i| lexical[i] > 0.0).collect();
        lexical_order.sort_by(|&a, &b| lexical[b].total_cmp(&lexical[a]));
        lexical_order.truncate(200);
        let mut semantic_order: Vec<_> = (0..corpus_len).collect();
        semantic_order.sort_by(|&a, &b| similarities[b].total_cmp(&similarities[a]));
        semantic_order.truncate(200);
        lexical_order.extend(semantic_order);
        lexical_order.extend(supplied);
        lexical_order
    };
    let mut selected = HashSet::new();
    order.retain(|&i| selected.insert(i));
    let semantic: Vec<_> = order.iter().map(|&i| similarities[i]).collect();
    let bm25_scores: Vec<_> = order.iter().map(|&i| lexical[i]).collect();
    let bm25_relative = relative_scores(&bm25_scores);
    let semantic_relative = relative_scores(&semantic);
    let score = |i: usize| (bm25_relative[i] + semantic_relative[i]) / 2.0;
    let mut fused: Vec<_> = (0..order.len()).collect();
    fused.sort_by(|&a, &b| {
        score(b)
            .total_cmp(&score(a))
            .then_with(|| bm25_scores[b].total_cmp(&bm25_scores[a]))
    });
    let mut chunks: Vec<_> = chunks.into_iter().map(Some).collect();
    let mut results: Vec<Chunk> = Vec::new();
    for i in fused {
        let mut chunk = chunks[order[i]].take().unwrap();
        if args.explain {
            chunk.scores = Some(Scores {
                bm25: bm25_scores[i],
                semantic: semantic[i],
                bm25_relative: bm25_relative[i],
                semantic_relative: semantic_relative[i],
                fused: score(i),
            });
        }
        if results
            .iter()
            .any(|c| c.path == chunk.path && c.start <= chunk.start && chunk.end <= c.end)
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
