use rayon::prelude::*;

use crate::{Model, Result, cache};

pub(crate) fn embed(
    texts: Vec<String>,
    model: &Model,
    cache: &cache::Cache,
) -> Result<Vec<Vec<f32>>> {
    let mut tokenizer: serde_json::Value =
        serde_json::from_slice(&cache.model_bytes(model, &model.tokenizer)?)?;
    tokenizer["truncation"] = serde_json::Value::Null;
    tokenizer["padding"] = serde_json::Value::Null;
    let weights = cache.model_bytes(model, &model.weights)?;
    let tensors = safetensors::SafeTensors::deserialize(&weights)?;
    let tensor = tensors.tensor("embeddings")?;
    if tensor.dtype() != model.dtype || tensor.shape() != [model.rows, 256] {
        return Err("unexpected model tensor".into());
    }
    let encoder = model2vec_rs::model::StaticModel::from_bytes(
        serde_json::to_vec(&tokenizer)?,
        &weights,
        b"{}",
        Some(true),
    )?;
    let vectors: Vec<_> = texts
        .par_chunks(32)
        .flat_map_iter(|batch| encoder.encode_with_args(batch, None, batch.len()))
        .collect();
    if !vectors.iter().flatten().all(|x| x.is_finite()) {
        return Err("non-finite embedding".into());
    }
    Ok(vectors)
}
