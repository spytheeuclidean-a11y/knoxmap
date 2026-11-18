//! Rules.txt terrain choices and Blends.txt edge overlays. The hash uses map
//! coordinates so selecting a single cell gives the same picks as a full row.
use super::building::tile_name;
use std::{
    collections::{HashMap, HashSet},
    fs,
    io::{Read, Seek, SeekFrom},
    path::Path,
};
const WIN: usize = 258;
const ORDER: [&str; 10] = [
    "0_Floor",
    "0_FloorOverlay",
    "0_FloorOverlay2",
    "0_FloorOverlay3",
    "0_FloorOverlay4",
    "0_FloorOverlay5",
    "0_FloorOverlay6",
    "0_Curbs",
    "0_Furniture",
    "0_Vegetation",
];
pub struct Strip {
    w: usize,
    top: i32,
    data: Vec<u32>,
}
impl Strip {
    pub fn read(path: &Path, y: i32, height: i32, width: i32) -> Result<Self, String> {
        let mut file = fs::File::open(path).map_err(|e| format!("{}: {e}", path.display()))?;
        let mut hdr = [0; 54];
        file.read_exact(&mut hdr).map_err(|e| e.to_string())?;
        let word = |i: usize| u32::from_le_bytes(hdr[i..i + 4].try_into().unwrap());
        let w = word(18) as i32;
        let signed = word(22) as i32;
        if &hdr[..2] != b"BM"
            || word(14) < 40
            || w != width
            || signed.unsigned_abs() != height as u32
            || hdr[28..30] != [24, 0]
            || word(30) != 0
        {
            return Err("source worker expects a plain 24-bit project bitmap".into());
        }
        let offset = word(10) as u64;
        let w = w as usize;
        let stride = (3 * w + 3) & !3;
        let top = y.clamp(0, height);
        let end = (y + WIN as i32).clamp(0, height);
        let mut data = vec![0; w * (end - top) as usize];
        let mut row = vec![0; stride];
        let first = if signed > 0 { height - end } else { top };
        file.seek(SeekFrom::Start(offset + first as u64 * stride as u64))
            .map_err(|e| e.to_string())?;
        for r in top..end {
            file.read_exact(&mut row).map_err(|e| e.to_string())?;
            let n = if signed > 0 { end - 1 - r } else { r - top } as usize;
            for (v, p) in data[n * w..(n + 1) * w].iter_mut().zip(row.chunks_exact(3)) {
                *v = u32::from_be_bytes([0, p[2], p[1], p[0]]);
            }
        }
        Ok(Self { w, top, data })
    }
    fn at(&self, x: i32, y: i32) -> Option<u32> {
        if x < 0 || x >= self.w as i32 || y < self.top {
            return None;
        }
        self.data
            .get((y - self.top) as usize * self.w + x as usize)
            .copied()
    }
}
type Fields = HashMap<String, Vec<String>>;
fn blocks(path: &Path) -> Result<Vec<(String, Fields)>, String> {
    let data = fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
    let text = String::from_utf8_lossy(&data);
    let mut lines = text.lines().map(|s| s.split("//").next().unwrap().trim());
    let mut blocks = Vec::new();
    while let Some(kind) = lines.next() {
        if !matches!(kind, "alias" | "rule" | "blend") {
            continue;
        }
        if lines.next() != Some("{") {
            continue;
        }
        let mut fields = Fields::new();
        while let Some(line) = lines.next() {
            if line == "}" {
                break;
            }
            if let Some((k, v)) = line.split_once('=') {
                let v = v.trim();
                let values = if v == "[" {
                    lines
                        .by_ref()
                        .take_while(|l| *l != "]")
                        .filter(|l| !l.is_empty())
                        .map(str::to_owned)
                        .collect()
                } else {
                    vec![v.to_owned()]
                };
                fields.insert(k.trim().to_owned(), values);
            }
        }
        blocks.push((kind.to_owned(), fields));
    }
    Ok(blocks)
}
fn field<'a>(f: &'a Fields, k: &str) -> Result<&'a str, String> {
    f.get(k)
        .and_then(|v| v.first())
        .map(String::as_str)
        .ok_or_else(|| format!("missing rule field {k}"))
}
fn color(s: &str) -> Result<u32, String> {
    let v: Vec<_> = s
        .split_whitespace()
        .map(str::parse::<u8>)
        .collect::<Result<_, _>>()
        .map_err(|e| e.to_string())?;
    if v.len() != 3 {
        return Err("invalid rule colour".into());
    }
    Ok(u32::from_be_bytes([0, v[0], v[1], v[2]]))
}
fn mix(x: i32, y: i32, salt: u64) -> u64 {
    let mut z = ((x as u64).wrapping_mul(0x9e3779b97f4a7c15)
        ^ (y as u64).wrapping_mul(0xc2b2ae3d27d4eb4f))
    .wrapping_add(salt.wrapping_mul(0x165667b19e3779f9));
    z = (z ^ (z >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94d049bb133111eb);
    z ^ (z >> 31)
}
struct Rule {
    index: usize,
    layer: usize,
    entries: Vec<Vec<u32>>,
    cond: Option<u32>,
    veg: bool,
}
struct Blend {
    layer: usize,
    main: HashSet<u32>,
    exclude: HashSet<u32>,
    tiles: Vec<u32>,
    dir: u8,
}
pub struct Terrain {
    pub names: Vec<String>,
    layers: Vec<String>,
    rules: HashMap<(bool, u32), Vec<Rule>>,
    blends: Vec<Blend>,
}
impl Terrain {
    pub fn load(path: &Path) -> Result<Self, String> {
        let rules = blocks(path)?;
        let blends = blocks(&path.with_file_name("Blends.txt"))?;
        let mut names = vec![String::new()];
        let mut ids = HashMap::from([(String::new(), 0)]);
        let mut intern = |name: &str| {
            *ids.entry(name.to_owned()).or_insert_with(|| {
                names.push(tile_name(name));
                (names.len() - 1) as u32
            })
        };
        let mut aliases = HashMap::new();
        for (kind, f) in &rules {
            if kind == "alias" {
                aliases.insert(
                    field(f, "name")?.to_owned(),
                    f.get("tiles")
                        .ok_or("missing alias tiles")?
                        .iter()
                        .map(|s| intern(s))
                        .collect::<Vec<_>>(),
                );
            }
        }
        let mut expand = |s: &str| aliases.get(s).cloned().unwrap_or_else(|| vec![intern(s)]);
        let mut layers: Vec<_> = rules
            .iter()
            .chain(&blends)
            .filter_map(|(_, f)| f.get("layer")?.first().cloned())
            .collect();
        layers.sort_by_key(|l| {
            (
                ORDER.iter().position(|v| v == l).unwrap_or(ORDER.len()),
                l.clone(),
            )
        });
        layers.dedup();
        let layer = |f: &Fields| -> Result<usize, String> {
            let s = field(f, "layer")?;
            layers
                .iter()
                .position(|v| v == s)
                .ok_or("unknown layer".into())
        };
        let mut by_color: HashMap<_, Vec<_>> = HashMap::new();
        for (index, (_, f)) in rules.iter().filter(|(k, _)| k == "rule").enumerate() {
            let bitmap = field(f, "bitmap")? == "1";
            let entries: Vec<_> = f
                .get("tiles")
                .ok_or("missing rule tiles")?
                .iter()
                .map(|s| expand(s))
                .collect();
            if entries.is_empty() || entries.iter().any(Vec::is_empty) {
                return Err("empty tile rule".into());
            }
            by_color
                .entry((bitmap, color(field(f, "color")?)?))
                .or_default()
                .push(Rule {
                    index,
                    layer: layer(f)?,
                    entries,
                    cond: f
                        .get("condition")
                        .and_then(|v| v.first())
                        .map(|s| color(s))
                        .transpose()?,
                    veg: bitmap && field(f, "layer")? == "0_Vegetation",
                });
        }
        let mut overlays = Vec::new();
        for (_, f) in blends {
            let dir = field(&f, "dir")?.bytes().try_fold(0, |d, c| {
                Ok::<_, String>(
                    d | match c {
                        b'n' => 1,
                        b's' => 2,
                        b'w' => 4,
                        b'e' => 8,
                        _ => return Err("unknown blend direction".into()),
                    },
                )
            })?;
            let tiles = expand(field(&f, "blendTile")?);
            if tiles.is_empty() {
                return Err("empty blend rule".into());
            }
            overlays.push(Blend {
                layer: layer(&f)?,
                main: expand(field(&f, "mainTile")?).into_iter().collect(),
                exclude: f
                    .get("exclude")
                    .into_iter()
                    .flatten()
                    .flat_map(|s| s.split_whitespace())
                    .flat_map(&mut expand)
                    .collect(),
                tiles,
                dir,
            });
        }
        Ok(Self {
            names,
            layers,
            rules: by_color,
            blends: overlays,
        })
    }
    pub fn cell(
        &self,
        land: &Strip,
        veg: &Strip,
        x0: i32,
        y0: i32,
        seed: u64,
        seams: bool,
    ) -> Vec<(bool, Vec<u32>)> {
        let mut layers = vec![Vec::new(); self.layers.len()];
        let salt = seed.wrapping_mul(1000003);
        for y in 0..WIN {
            for x in 0..WIN {
                let (px, py) = (x0 + x as i32 - 1, y0 + y as i32 - 1);
                let Some(l) = land.at(px, py) else { continue };
                let v = veg.at(px, py).unwrap_or(0);
                let a = self.rules.get(&(false, l)).into_iter().flatten();
                let b = self.rules.get(&(true, v)).into_iter().flatten();
                let mut a = a.peekable();
                let mut b = b.peekable();
                while let Some(r) = match (a.peek(), b.peek()) {
                    (Some(l), Some(r)) if l.index > r.index => b.next(),
                    (Some(_), _) => a.next(),
                    _ => b.next(),
                } {
                    if r.cond.is_some_and(|c| c != l)
                        || r.veg
                            && matches!(
                                l,
                                0x646464
                                    | 0x969696
                                    | 0xa5a08c
                                    | 0x505050
                                    | 0x787878
                                    | 0x6e6464
                                    | 0x827878
                                    | 0x008aff
                            )
                    {
                        continue;
                    }
                    let s = salt.wrapping_add(r.index as u64);
                    let options = &r.entries[(mix(px, py, s) % r.entries.len() as u64) as usize];
                    let id = options
                        [(mix(px, py, s.wrapping_add(7919)) % options.len() as u64) as usize];
                    if layers[r.layer].is_empty() {
                        layers[r.layer].resize(WIN * WIN, 0);
                    }
                    layers[r.layer][y * WIN + x] = id;
                }
            }
        }
        if let Some(i) = self
            .layers
            .iter()
            .position(|s| s == "0_Floor")
            .filter(|i| !layers[*i].is_empty())
        {
            let floor = &layers[i];
            let seen: HashSet<_> = floor.iter().copied().collect();
            let mut result = HashMap::new();
            for (n, b) in self.blends.iter().enumerate() {
                if b.main.is_disjoint(&seen) {
                    continue;
                }
                let main: Vec<_> = floor
                    .iter()
                    .map(|v| *v != 0 && b.main.contains(v))
                    .collect();
                for y in 0..WIN {
                    for x in 0..WIN {
                        let j = y * WIN + x;
                        if floor[j] == 0 || main[j] || b.exclude.contains(&floor[j]) {
                            continue;
                        }
                        let (px, py) = (x0 + x as i32 - 1, y0 + y as i32 - 1);
                        let mut mask = 0;
                        for (dx, dy, bit) in [(0, -1, 1), (0, 1, 2), (-1, 0, 4), (1, 0, 8)] {
                            let (nx, ny) = (x as i32 + dx, y as i32 + dy);
                            if nx >= 0
                                && ny >= 0
                                && nx < WIN as i32
                                && ny < WIN as i32
                                && main[ny as usize * WIN + nx as usize]
                                && (!seams
                                    || (px.div_euclid(300) == (px + dx).div_euclid(300)
                                        && py.div_euclid(300) == (py + dy).div_euclid(300)))
                            {
                                mask |= bit;
                            }
                        }
                        if mask & b.dir != b.dir
                            || b.dir.count_ones() == 1
                                && ((b.dir & 3 != 0 && mask & 12 != 0)
                                    || (b.dir & 12 != 0 && mask & 3 != 0))
                        {
                            continue;
                        }
                        result.entry(b.layer).or_insert_with(|| vec![0; WIN * WIN])[j] = b.tiles
                            [(mix(px, py, salt.wrapping_add(5000 + n as u64))
                                % b.tiles.len() as u64) as usize];
                    }
                }
            }
            for (i, v) in result {
                layers[i] = v;
            }
        }
        layers
            .into_iter()
            .enumerate()
            .filter(|(_, v)| !v.is_empty())
            .map(|(i, v)| (self.layers[i] == "0_Furniture", v))
            .collect()
    }
}
