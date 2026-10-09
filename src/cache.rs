use sha2::{Digest, Sha256};
use std::fs::{File, OpenOptions};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime};

use super::{Model, Result};

pub struct Cache {
    hub: PathBuf,
    _temporary: Option<tempfile::TempDir>,
}

pub fn offline() -> bool {
    matches!(
        std::env::var("HF_HUB_OFFLINE")
            .unwrap_or_default()
            .to_uppercase()
            .as_str(),
        "1" | "TRUE" | "YES" | "ON"
    )
}

impl Cache {
    pub fn new(directory: Option<&Path>, refresh: bool) -> Result<Self> {
        if refresh && offline() {
            return Err("--fresh-assets requires downloads; unset HF_HUB_OFFLINE first".into());
        }
        let temporary = if refresh {
            Some(
                tempfile::Builder::new()
                    .prefix("sgrep-refresh-")
                    .tempdir()?,
            )
        } else {
            None
        };
        let directory = temporary.as_ref().map(|dir| dir.path()).or(directory);
        if let Some(directory) = directory {
            tree_sitter_language_pack::configure(&tree_sitter_language_pack::PackConfig {
                cache_dir: Some(directory.to_path_buf()),
                ..Default::default()
            })?;
        }
        let hub = directory.map(|dir| dir.join("hub")).unwrap_or_else(|| {
            std::env::var_os("HF_HUB_CACHE")
                .or_else(|| std::env::var_os("HUGGINGFACE_HUB_CACHE"))
                .map(PathBuf::from)
                .unwrap_or_else(|| hf_hub::Cache::from_env().path().clone())
        });
        Ok(Self {
            hub,
            _temporary: temporary,
        })
    }

    pub fn model_bytes(&self, model: &Model, asset: &Asset) -> Result<Vec<u8>> {
        let file = self
            .hub
            .join(format!("models--{}", model.repo.replace('/', "--")))
            .join("snapshots")
            .join(model.revision)
            .join(asset.name);
        if let Some(bytes) = asset.read_verified(&file)? {
            return Ok(bytes);
        }
        if offline() {
            return Err(format!(
                "{} {} is not cached or failed integrity verification; run once online to download or repair it",
                model.repo, asset.name
            )
            .into());
        }
        let repository = self
            .hub
            .join(format!("models--{}", model.repo.replace('/', "--")));
        std::fs::create_dir_all(&repository)?;
        let lock = std::fs::OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(repository.join(".sgrep.lock"))?;
        lock.lock()?;
        if let Some(bytes) = asset.read_verified(&file)? {
            return Ok(bytes);
        }
        match std::fs::remove_file(&file) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        let api = hf_hub::api::sync::ApiBuilder::from_env()
            .with_cache_dir(self.hub.clone())
            .with_progress(false)
            .build()?;
        let downloaded = api
            .repo(hf_hub::Repo::with_revision(
                model.repo.into(),
                hf_hub::RepoType::Model,
                model.revision.into(),
            ))
            .download(asset.name)?;
        asset.read_verified(&downloaded)?.ok_or_else(|| {
            format!(
                "{} {} failed integrity verification after download",
                model.repo, asset.name
            )
            .into()
        })
    }
}

pub struct Asset {
    pub name: &'static str,
    pub size: u64,
    pub sha256: &'static str,
}

impl Asset {
    fn read_verified(&self, path: &Path) -> Result<Option<Vec<u8>>> {
        let file = match std::fs::File::open(path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        };
        if file.metadata()?.len() != self.size {
            return Ok(None);
        }
        let mut bytes = Vec::with_capacity(self.size as usize);
        file.take(self.size + 1).read_to_end(&mut bytes)?;
        let digest: String = Sha256::digest(&bytes)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        if bytes.len() as u64 != self.size || digest != self.sha256 {
            return Ok(None);
        }
        Ok(Some(bytes))
    }
}

const MAX_BYTES: u64 = 256 * 1024 * 1024;
const MAX_ENTRIES: usize = 128;
const MAX_AGE: Duration = Duration::from_secs(30 * 86400);

pub struct IndexCache {
    pub directory: PathBuf,
    pub max_bytes: u64,
}

impl IndexCache {
    pub fn new(directory: Option<&Path>) -> Result<Option<Self>> {
        let max_bytes = std::env::var("SGREP_CACHE_MAX_BYTES")
            .ok()
            .map(|value| value.parse::<u64>())
            .transpose()
            .map_err(|_| "SGREP_CACHE_MAX_BYTES must be a non-negative integer")?
            .unwrap_or(MAX_BYTES);
        let directory = directory
            .map(|p| p.join("index"))
            .or_else(|| std::env::var_os("SGREP_CACHE_DIR").map(PathBuf::from))
            .or_else(|| std::env::var_os("XDG_CACHE_HOME").map(|p| Path::new(&p).join("sgrep")))
            .or_else(|| std::env::var_os("HOME").map(|p| Path::new(&p).join(".cache/sgrep")));
        Ok(directory.filter(|_| max_bytes > 0).map(|directory| Self {
            directory,
            max_bytes,
        }))
    }

    pub fn maintain(&self, replacing: Option<(&Path, u64)>) -> Result<File> {
        let lock = lock(&self.directory)?;
        prune(&self.directory, self.max_bytes, replacing)?;
        Ok(lock)
    }
}

fn lock(directory: &Path) -> Result<File> {
    std::fs::create_dir_all(directory)?;
    let file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(directory.join(".sgrep-index.lock"))?;
    file.lock()?;
    Ok(file)
}

fn prune(directory: &Path, max_bytes: u64, replacing: Option<(&Path, u64)>) -> Result<()> {
    let mut entries = Vec::new();
    let now = SystemTime::now();
    for entry in std::fs::read_dir(directory)? {
        let entry = entry?;
        if !entry.file_type()?.is_file() {
            continue;
        }
        let name = entry.file_name();
        let name = name.to_string_lossy();
        let temporary = (name.starts_with("sgrep-index-") || name.starts_with("sgrep-embedding-"))
            && name.ends_with(".tmp");
        let owned = name
            .strip_prefix("index-")
            .unwrap_or(&name)
            .strip_suffix(".bin")
            .is_some_and(|name| name.len() == 64 && name.bytes().all(|b| b.is_ascii_hexdigit()));
        if !owned && !temporary {
            continue;
        }
        let path = entry.path();
        if replacing.is_some_and(|(file, _)| file == path) {
            continue;
        }
        let metadata = entry.metadata()?;
        let modified = metadata.modified()?;
        if temporary || now.duration_since(modified).unwrap_or_default() > MAX_AGE {
            std::fs::remove_file(path)?;
        } else {
            entries.push((modified, path, metadata.len()));
        }
    }
    entries.sort_unstable();
    let mut bytes = entries.iter().map(|(_, _, size)| size).sum::<u64>()
        + replacing.map_or(0, |(_, size)| size);
    let mut count = entries.len() + usize::from(replacing.is_some());
    for (_, path, size) in entries {
        if bytes <= max_bytes && count <= MAX_ENTRIES {
            break;
        }
        std::fs::remove_file(path)?;
        bytes -= size;
        count -= 1;
    }
    Ok(())
}
