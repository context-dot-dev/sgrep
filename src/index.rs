//! Query-independent chunks, postings and vectors, published atomically.
use crate::{Args, CODE, Chunk, ModelChoice, Result, TEXT, candidates, embed, rank, source_files};
use memmap2::Mmap;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, HashSet},
    fs::File,
    io::Write,
    path::Path,
};

#[derive(Serialize, Deserialize, PartialEq)]
struct Stamp {
    path: std::path::PathBuf,
    len: u64,
    modified: u128,
    #[cfg(not(unix))]
    digest: [u8; 32],
    #[cfg(unix)]
    identity: (u64, u64, i64, i64),
}

fn manifest(path: &Path) -> Result<Vec<Stamp>> {
    let (root, files) = source_files(path)?;
    files
        .into_iter()
        .map(|path| {
            let metadata = std::fs::metadata(root.join(&path))?;
            #[cfg(not(unix))]
            let digest = Sha256::digest(std::fs::read(root.join(&path))?).into();
            Ok(Stamp {
                #[cfg(not(unix))]
                digest,
                path,
                len: metadata.len(),
                modified: metadata
                    .modified()?
                    .duration_since(std::time::UNIX_EPOCH)?
                    .as_nanos(),
                #[cfg(unix)]
                identity: {
                    use std::os::unix::fs::MetadataExt;
                    (
                        metadata.dev(),
                        metadata.ino(),
                        metadata.ctime(),
                        metadata.ctime_nsec(),
                    )
                },
            })
        })
        .collect()
}

#[derive(Serialize, Deserialize)]
struct Header {
    version: u32,
    manifest: Vec<Stamp>,
    revision: String,
    count: usize,
    total_length: usize,
    vectors: usize,
    chunks: usize,
    terms: usize,
    term_count: usize,
}

fn put(out: &mut Vec<u8>, n: usize) {
    out.extend_from_slice(&(n as u64).to_le_bytes());
}
fn number(data: &[u8], offset: usize) -> Result<usize> {
    let bytes = data
        .get(offset..offset.checked_add(8).ok_or("index overflow")?)
        .ok_or("truncated index")?;
    Ok(usize::try_from(u64::from_le_bytes(bytes.try_into()?))?)
}
fn record(data: &[u8], table: usize, i: usize) -> Result<&[u8]> {
    let at = table
        .checked_add(i.checked_mul(8).ok_or("index overflow")?)
        .ok_or("index overflow")?;
    let start = number(data, at)?;
    let end = number(data, at + 8)?;
    data.get(start..end)
        .ok_or_else(|| "invalid index record".into())
}
fn records(out: &mut Vec<u8>, rows: impl IntoIterator<Item = Vec<u8>>) -> usize {
    let rows: Vec<_> = rows.into_iter().collect();
    let table = out.len();
    let mut offset = table + (rows.len() + 1) * 8;
    for row in &rows {
        put(out, offset);
        offset += row.len();
    }
    put(out, offset);
    for row in rows {
        out.extend(row);
    }
    table
}

struct Index {
    map: Mmap,
    header: Header,
    start: usize,
}
impl Index {
    fn open(file: &Path, stamps: &[Stamp], choice: ModelChoice) -> Result<Self> {
        let file = File::open(file)?;
        // Writers replace the cache atomically; mapped files are never modified in place.
        let map = unsafe { Mmap::map(&file)? };
        if map.get(..8) != Some(b"SGREPIX1") {
            return Err("invalid index magic".into());
        }
        let start = 16usize
            .checked_add(number(&map, 8)?)
            .ok_or("index overflow")?;
        let header: Header = serde_json::from_slice(map.get(16..start).ok_or("truncated index")?)?;
        if header.version != 3
            || header.manifest != stamps
            || (choice == ModelChoice::Code && header.revision != CODE.revision)
            || (choice == ModelChoice::Text && header.revision != TEXT.revision)
            || ![CODE.revision, TEXT.revision].contains(&header.revision.as_str())
        {
            return Err("stale index".into());
        }
        let end = map.len().checked_sub(4).ok_or("truncated index")?;
        let checksum = u32::from_le_bytes(map.get(end..).ok_or("truncated index")?.try_into()?);
        if crc32fast::hash(map.get(..end).ok_or("truncated index")?) != checksum {
            return Err("corrupt index".into());
        }
        let index = Self { map, header, start };
        let n = index.header.count;
        if n.checked_mul(256 * 4)
            .and_then(|len| index.header.vectors.checked_add(len))
            .is_none_or(|end| end > index.data().len())
        {
            return Err("invalid vector index".into());
        }
        Ok(index)
    }
    fn data(&self) -> &[u8] {
        &self.map[self.start..self.map.len() - 4]
    }
    fn lexical(&self, terms: &[String]) -> Result<Vec<f64>> {
        let h = &self.header;
        let data = self.data();
        let mut scores = vec![0.0; h.count];
        for term in terms {
            let mut low = 0;
            let mut high = h.term_count;
            while low < high {
                let mid = (low + high) / 2;
                let row = record(data, h.terms, mid)?;
                let len = number(row, 0)?;
                let word = row.get(8..8 + len).ok_or("invalid posting")?;
                match word.cmp(term.as_bytes()) {
                    std::cmp::Ordering::Less => low = mid + 1,
                    std::cmp::Ordering::Greater => high = mid,
                    std::cmp::Ordering::Equal => {
                        let postings = row.get(8 + len..).ok_or("invalid posting")?;
                        if postings.len() % 24 != 0 {
                            return Err("invalid posting size".into());
                        }
                        let df = (postings.len() / 24) as f64;
                        let idf = (1.0 + (h.count as f64 - df + 0.5) / (df + 0.5)).ln();
                        for posting in postings.chunks_exact(24) {
                            let id = number(posting, 0)?;
                            let count = number(posting, 8)? as f64;
                            let length = number(posting, 16)? as f64;
                            *scores.get_mut(id).ok_or("invalid posting id")? += idf * count * 2.5
                                / (count
                                    + 1.5
                                        * (0.25
                                            + 0.75 * length
                                                / (h.total_length as f64 / h.count.max(1) as f64)
                                                    .max(1.0)));
                        }
                        break;
                    }
                }
            }
        }
        Ok(scores)
    }
    fn search(&self, args: &Args, terms: &[String]) -> Result<Vec<Chunk>> {
        let model = if self.header.revision == CODE.revision {
            &CODE
        } else {
            &TEXT
        };
        let query = embed(vec![args.query.clone()], model)?.remove(0);
        let lexical = self.lexical(terms)?;
        let vectors = &self.data()[self.header.vectors..][..self.header.count * 256 * 4];
        let similarities: Vec<f64> = vectors
            .chunks_exact(256 * 4)
            .map(|row| {
                row.chunks_exact(4)
                    .zip(&query)
                    .map(|(v, q)| f32::from_le_bytes(v.try_into().unwrap()) * q)
                    .sum::<f32>() as f64
            })
            .collect();
        if similarities.iter().any(|s| !s.is_finite()) {
            return Err("invalid index vector".into());
        }
        rank(
            args,
            self.header.count,
            &lexical,
            &similarities,
            Vec::new(),
            |i| {
                Ok(serde_json::from_slice(record(
                    self.data(),
                    self.header.chunks,
                    i,
                )?)?)
            },
        )
    }
}

fn build(args: &Args, path: &Path, stamps: Vec<Stamp>, file: &Path) -> Result<()> {
    let mut chunks = candidates(path)?;
    let mut seen = HashSet::new();
    chunks.retain(|c| seen.insert((c.path.clone(), c.start, c.end)));
    let prose = chunks.iter().all(|c| crate::is_prose(&c.path));
    let model = if args.model == ModelChoice::Text || (args.model == ModelChoice::Auto && prose) {
        &TEXT
    } else {
        &CODE
    };
    let vectors = if chunks.is_empty() {
        Vec::new()
    } else {
        embed(
            chunks
                .iter()
                .map(|c| format!("{}\n{}", c.path, c.content))
                .collect(),
            model,
        )?
    };
    let mut data = Vec::new();
    for row in vectors {
        for value in row {
            data.extend_from_slice(&value.to_le_bytes());
        }
    }
    let mut postings: BTreeMap<&str, Vec<u8>> = BTreeMap::new();
    let mut total = 0usize;
    for (i, chunk) in chunks.iter().enumerate() {
        let length = chunk.counts.values().sum::<usize>();
        total += length;
        for (term, count) in &chunk.counts {
            let row = postings.entry(term).or_default();
            put(row, i);
            put(row, *count);
            put(row, length);
        }
    }
    let chunk_table = records(
        &mut data,
        chunks
            .iter()
            .map(serde_json::to_vec)
            .collect::<std::result::Result<Vec<_>, _>>()?,
    );
    let term_count = postings.len();
    let terms = records(
        &mut data,
        postings.into_iter().map(|(term, posting)| {
            let mut row = Vec::new();
            put(&mut row, term.len());
            row.extend_from_slice(term.as_bytes());
            row.extend(posting);
            row
        }),
    );
    // Do not publish a snapshot if files changed during construction.
    if manifest(path)? != stamps {
        return Err("source changed while building index; retry search".into());
    }
    let header = Header {
        version: 3,
        manifest: stamps,
        revision: model.revision.into(),
        count: chunks.len(),
        total_length: total,
        vectors: 0,
        chunks: chunk_table,
        terms,
        term_count,
    };
    let header = serde_json::to_vec(&header)?;
    let mut bytes = b"SGREPIX1".to_vec();
    put(&mut bytes, header.len());
    bytes.extend(header);
    bytes.extend(data);
    let checksum = crc32fast::hash(&bytes);
    bytes.extend_from_slice(&checksum.to_le_bytes());
    let directory = file.parent().unwrap();
    std::fs::create_dir_all(directory)?;
    let mut temporary = tempfile::NamedTempFile::new_in(directory)?;
    temporary.write_all(&bytes)?;
    temporary.persist(file)?;
    Ok(())
}

pub fn search(args: &Args, path: &Path, terms: &[String]) -> Result<Option<Vec<Chunk>>> {
    let directory = std::env::var_os("SGREP_CACHE_DIR")
        .map(std::path::PathBuf::from)
        .or_else(|| std::env::var_os("XDG_CACHE_HOME").map(|p| Path::new(&p).join("sgrep")))
        .or_else(|| std::env::var_os("HOME").map(|p| Path::new(&p).join(".cache/sgrep")));
    let Some(directory) = directory else {
        return Ok(None);
    };
    let mut identity = Sha256::new();
    identity.update(path.as_os_str().as_encoded_bytes());
    identity.update([args.model as u8]);
    let name: String = identity
        .finalize()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    let file = directory.join(format!("index-{name}.bin"));
    let stamps = manifest(path)?;
    if stamps.is_empty() {
        return Ok(Some(Vec::new()));
    }
    if let Ok(index) = Index::open(&file, &stamps, args.model) {
        if index.header.count == 0 {
            return Ok(Some(Vec::new()));
        }
        if let Ok(results) = index.search(args, terms) {
            return Ok(Some(results));
        }
    }
    if let Err(error) = build(args, path, stamps, file.as_path()) {
        eprintln!("sgrep: could not save search index: {error}");
        return Ok(None);
    }
    let index = Index::open(&file, &manifest(path)?, args.model)?;
    if index.header.count == 0 {
        return Ok(Some(Vec::new()));
    }
    Ok(Some(index.search(args, terms)?))
}
