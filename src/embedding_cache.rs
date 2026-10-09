use crate::{Model, Result, embed};
use sha2::{Digest, Sha256};
use std::io::Write;
use std::path::Path;

pub fn corpus(
    texts: Vec<String>,
    model: &Model,
    scope: &Path,
    disabled: bool,
) -> Result<Vec<Vec<f32>>> {
    let directory = std::env::var_os("SGREP_CACHE_DIR")
        .map(std::path::PathBuf::from)
        .or_else(|| std::env::var_os("XDG_CACHE_HOME").map(|p| Path::new(&p).join("sgrep")))
        .or_else(|| std::env::var_os("HOME").map(|p| Path::new(&p).join(".cache/sgrep")));
    let Some(directory) = directory.filter(|_| !disabled) else {
        return embed(texts, model);
    };
    let mut identity = Sha256::new();
    identity.update(scope.as_os_str().as_encoded_bytes());
    identity.update(model.revision);
    let name: String = identity
        .finalize()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    let file = directory.join(format!("{name}.bin"));
    let mut fingerprint = Sha256::new();
    fingerprint.update(b"sgrep-embeddings-v1");
    fingerprint.update(model.revision);
    for text in &texts {
        fingerprint.update((text.len() as u64).to_le_bytes());
        fingerprint.update(text.as_bytes());
    }
    let fingerprint = fingerprint.finalize();
    if let Ok(bytes) = std::fs::read(&file) {
        let payload_len = texts.len().checked_mul(256 * 4);
        if payload_len.and_then(|n| n.checked_add(64)) == Some(bytes.len())
            && bytes[..32] == fingerprint[..]
            && bytes[32..64] == Sha256::digest(&bytes[64..])[..]
        {
            let vectors: Vec<Vec<f32>> = bytes[64..]
                .chunks_exact(256 * 4)
                .map(|row| {
                    row.chunks_exact(4)
                        .map(|v| f32::from_le_bytes(v.try_into().unwrap()))
                        .collect()
                })
                .collect();
            if vectors.iter().flatten().all(|v| v.is_finite()) {
                return Ok(vectors);
            }
        }
    }
    let vectors = embed(texts, model)?;
    let payload: Vec<u8> = vectors
        .iter()
        .flatten()
        .flat_map(|v| v.to_le_bytes())
        .collect();
    let save = || -> Result<()> {
        std::fs::create_dir_all(&directory)?;
        let mut temporary = tempfile::NamedTempFile::new_in(&directory)?;
        temporary.write_all(&fingerprint)?;
        temporary.write_all(&Sha256::digest(&payload))?;
        temporary.write_all(&payload)?;
        temporary.persist(&file)?;
        Ok(())
    };
    if let Err(error) = save() {
        eprintln!("sgrep: could not save embedding cache: {error}");
    }
    Ok(vectors)
}
