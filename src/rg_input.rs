use crate::{Chunk, Result, filename, make_chunk};
use base64::{Engine, engine::general_purpose::STANDARD};
use serde::Deserialize;
use serde_json::Value;
use std::collections::HashMap;
use std::io::{self, BufRead};
use std::path::{Path, PathBuf};

#[derive(Deserialize)]
struct Event {
    #[serde(rename = "type")]
    kind: String,
    data: Value,
}

fn bytes(value: &Value) -> Result<Vec<u8>> {
    if let Some(text) = value.get("text").and_then(Value::as_str) {
        Ok(text.as_bytes().to_vec())
    } else if let Some(encoded) = value.get("bytes").and_then(Value::as_str) {
        Ok(STANDARD.decode(encoded)?)
    } else {
        Err("rg JSON requires a text or base64 bytes field".into())
    }
}

struct Group {
    path: String,
    start: usize,
    end: usize,
    content: String,
}

pub fn read(input: &Path, scope: &Path) -> Result<Vec<Chunk>> {
    let reader: Box<dyn BufRead> = if input == Path::new("-") {
        Box::new(io::stdin().lock())
    } else {
        Box::new(io::BufReader::new(std::fs::File::open(input)?))
    };
    let root = if scope.is_dir() {
        scope
    } else {
        scope.parent().unwrap()
    };
    let mut source: HashMap<PathBuf, Vec<String>> = HashMap::new();
    let mut paths: HashMap<Vec<u8>, PathBuf> = HashMap::new();
    let mut groups: Vec<Group> = Vec::new();
    for line in reader.lines() {
        let event: Event = serde_json::from_str(&line?)?;
        match event.kind.as_str() {
            "begin" | "end" | "summary" => continue,
            "match" | "context" => {}
            _ => return Err("unrecognized rg JSON event".into()),
        }
        let raw_path = bytes(&event.data["path"])?;
        let path = if let Some(path) = paths.get(&raw_path) {
            path.clone()
        } else {
            let path = filename(&raw_path).canonicalize()?;
            paths.insert(raw_path, path.clone());
            path
        };
        if !path.starts_with(root) || (scope.is_file() && path != scope) {
            return Err("rg JSON path is outside the search scope".into());
        }
        let start = event.data["line_number"]
            .as_u64()
            .and_then(|n| usize::try_from(n).ok())
            .filter(|&n| n > 0)
            .ok_or("rg JSON requires a positive line_number")?;
        let raw = bytes(&event.data["lines"])?;
        let content = String::from_utf8_lossy(&raw)
            .replace("\r\n", "\n")
            .replace('\r', "\n");
        let count = content.split_inclusive('\n').count();
        let end = start
            .checked_add(count)
            .and_then(|n| n.checked_sub(1))
            .filter(|_| count > 0)
            .ok_or("invalid rg JSON line range")?;
        if !source.contains_key(&path) {
            let raw = std::fs::read(&path)?;
            if raw.contains(&0) {
                return Err("rg JSON refers to a binary file".into());
            }
            source.insert(
                path.clone(),
                String::from_utf8_lossy(&raw)
                    .replace("\r\n", "\n")
                    .replace('\r', "\n")
                    .split_inclusive('\n')
                    .map(str::to_owned)
                    .collect(),
            );
        }
        let lines = &source[&path];
        if end > lines.len() || lines[start - 1..end].concat() != content {
            return Err("rg JSON does not match current source; rerun ripgrep".into());
        }
        let relative = path.strip_prefix(root)?.to_string_lossy().into_owned();
        if let Some(last) = groups
            .last_mut()
            .filter(|g| g.path == relative && g.end.checked_add(1) == Some(start))
        {
            last.content.push_str(&content);
            last.end = end;
        } else {
            groups.push(Group {
                path: relative,
                start,
                end,
                content,
            });
        }
    }
    Ok(groups
        .into_iter()
        .map(|g| make_chunk(g.path, g.start, g.end, g.content))
        .collect())
}
