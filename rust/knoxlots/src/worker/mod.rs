//! Rust source preparation for the knoxlots backend. The coordinator provides
//! a job per row and the selected columns. Buildings are composed in project
//! order, while terrain is read one strip at a time. Only a successful worker
//! exit allows the coordinator to checkpoint the row.
mod building;
mod roof;
mod rooms;
mod terrain;

use self::building::{Building, Stack};
use knoxlots::{
    cell::{Cell, Square},
    header::Room,
    kcell::KCell,
};
use std::{
    collections::{BTreeMap, BTreeSet, HashMap, HashSet},
    fs,
    path::{Path, PathBuf},
};

type Node<'a> = roxmltree::Node<'a, 'a>;
type Point = (i32, i32);
fn attr<'a>(n: Node<'a>, key: &str) -> &'a str {
    n.attribute(key).unwrap_or("")
}
fn number(n: Node, k: &str) -> Result<i32, String> {
    attr(n, k)
        .parse()
        .map_err(|_| format!("invalid {} attribute {k}", n.tag_name().name()))
}
fn children<'a, 'b>(n: Node<'a>, tag: &'b str) -> impl Iterator<Item = Node<'a>> + 'b
where
    'a: 'b,
{
    n.children().filter(move |c| c.has_tag_name(tag))
}
fn xml(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('"', "&quot;")
        .replace('\r', "&#13;")
        .replace('\n', "&#10;")
        .replace('\t', "&#9;")
}
fn lot_path(project: &Path, name: &str) -> Result<PathBuf, String> {
    if name.is_empty() || name.contains(['/', '\\']) || name.contains(':') {
        return Err(format!("invalid building name {name}"));
    }
    Ok(project.join("buildings").join(format!("{name}.tbx")))
}
pub fn run(path: &str) -> Result<(), String> {
    let input = fs::read_to_string(path).map_err(|e| e.to_string())?;
    let doc = roxmltree::Document::parse(&input).map_err(|e| e.to_string())?;
    let job = doc.root_element();
    let project = Path::new(attr(job, "project"));
    let out = Path::new(attr(job, "out"));
    match job.tag_name().name() {
        "tables" => rooms::prepare(job, project, out),
        "row" => row(job, project, out),
        "changes" => changed_cells(job, project, out),
        other => Err(format!("unknown source job {other}")),
    }
}
/// The same tile and room footprint as the row compositor, including
/// outside-wall props that extend past the lot's rectangle.
fn changed_cells(job: Node, project: &Path, out: &Path) -> Result<(), String> {
    let (ox, oy, margin) = (
        number(job, "ox")?,
        number(job, "oy")?,
        number(job, "margin")?,
    );
    let mut cache = HashMap::new();
    let mut dirty = BTreeSet::new();
    for lot in children(job, "lot") {
        let name = attr(lot, "name");
        let (tx, ty) = (number(lot, "x")?, number(lot, "y")?);
        if !cache.contains_key(name) {
            let data =
                fs::read_to_string(lot_path(project, name)?).map_err(|e| format!("{name}: {e}"))?;
            let doc = roxmltree::Document::parse(&data).map_err(|e| e.to_string())?;
            let b = Building::parse(doc.root_element(), false)?;
            let mut points = HashSet::new();
            for (z, f) in b.floors.iter().enumerate() {
                points.extend(building::level(&b, z)?.into_keys());
                points.extend(
                    f.rooms
                        .iter()
                        .enumerate()
                        .filter(|(_, r)| **r > 0)
                        .map(|(n, _)| (n as i32 % b.w, n as i32 / b.w)),
                );
            }
            cache.insert(name, (b.h, points));
        }
        let (height, points) = &cache[name];
        for &(x, y) in points {
            let cy = (ty + y + oy).div_euclid(256);
            let y0 = cy * 256 - oy;
            if ty - margin < y0 + 256 + margin && ty + height + margin > y0 - margin {
                dirty.insert(((tx + x + ox).div_euclid(256), cy));
            }
        }
    }
    let mut result = String::new();
    for (x, y) in dirty {
        result.push_str(&format!("{x} {y}\n"));
    }
    fs::write(out, result).map_err(|e| e.to_string())
}
fn row(job: Node, project: &Path, out: &Path) -> Result<(), String> {
    let (ox, oy) = (number(job, "ox")?, number(job, "oy")?);
    let cy = number(job, "cy")?;
    let y0 = cy * 256 - oy;
    let (w, h) = (number(job, "width")?, number(job, "height")?);
    let seed = attr(job, "seed")
        .parse::<i64>()
        .map_err(|_| "invalid seed")? as u64;
    let name = project
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or("invalid project name")?;
    let land = terrain::Strip::read(&project.join(format!("{name}.bmp")), y0 - 1, h, w)?;
    let veg = terrain::Strip::read(&project.join(format!("{name}_veg.bmp")), y0 - 1, h, w)?;
    let terrain = terrain::Terrain::load(Path::new(attr(job, "rules")))?;
    let mut world: HashMap<(i32, i32, i32), Stack> = HashMap::new();
    let mut interiors = HashSet::new();
    let mut footprints: BTreeMap<&str, BTreeSet<i32>> = BTreeMap::new();
    let track = job.attribute("footprints").is_some();
    for lot in children(job, "lot") {
        let name = attr(lot, "name");
        let (tx, ty, base) = (number(lot, "x")?, number(lot, "y")?, number(lot, "z")?);
        let path = lot_path(project, name)?;
        let data = fs::read_to_string(&path).map_err(|e| format!("{}: {e}", path.display()))?;
        let doc = roxmltree::Document::parse(&data).map_err(|e| format!("{name}: {e}"))?;
        let b = Building::parse(doc.root_element(), false).map_err(|e| format!("{name}: {e}"))?;
        for (z, f) in b.floors.iter().enumerate() {
            let mut layers = building::level(&b, z).map_err(|e| format!("{name}: {e}"))?;
            for (n, &rid) in f.rooms.iter().enumerate() {
                if rid != 0 {
                    layers.entry((n as i32 % b.w, n as i32 / b.w)).or_default();
                }
            }
            for ((x, y), new) in layers {
                let (wx, wy, lv) = (tx + x, ty + y, base + z as i32);
                if !(y0..y0 + 256).contains(&wy) {
                    continue;
                }
                let cx = (wx + ox).div_euclid(256);
                if track && cx >= ox.div_euclid(256) && cx <= (ox + w - 1).div_euclid(256) {
                    footprints.entry(name).or_default().insert(cx);
                }
                let room = b.room(z, x, y) > 0;
                if room && lv == 0 {
                    interiors.insert((wx, wy));
                }
                building::compose(world.entry((wx, wy, lv)).or_default(), new, room);
            }
        }
    }
    let mut by_column: HashMap<i32, Vec<_>> = HashMap::new();
    for ((x, y, z), mut stack) in world {
        building::finish(&mut stack);
        if !stack.is_empty() {
            by_column
                .entry((x + ox).div_euclid(256))
                .or_default()
                .push((x, y, z, stack));
        }
    }
    for col in children(job, "cell") {
        let cx = number(col, "x")?;
        let x0 = cx * 256 - ox;
        let mut rooms = Vec::new();
        let mut buildings = Vec::new();
        for g in children(col, "building") {
            let start = rooms.len() as u32;
            for r in children(g, "room") {
                let nums: Vec<i32> = r
                    .text()
                    .unwrap_or("")
                    .split_whitespace()
                    .map(str::parse)
                    .collect::<Result<_, _>>()
                    .map_err(|_| "invalid room rectangle")?;
                if nums.len() % 4 != 0 {
                    return Err("incomplete room rectangle".into());
                }
                rooms.push(Room {
                    name: attr(r, "name").to_owned(),
                    z: number(r, "z")?,
                    rects: nums
                        .chunks_exact(4)
                        .map(|r| {
                            let rect = [r[0] - x0, r[1] - y0, r[2], r[3]];
                            if rect.iter().any(|v| *v < 0) {
                                return Err("negative room rectangle");
                            }
                            Ok(rect.map(|v| v as u32))
                        })
                        .collect::<Result<_, _>>()?,
                    objects: vec![],
                });
            }
            buildings.push((start..rooms.len() as u32).collect());
        }
        let mut stacks = by_column.remove(&cx).unwrap_or_default();
        // Stable palette numbering even when a new worker gets a different hash seed.
        stacks.sort_unstable_by_key(|(x, y, z, _)| (*z, *y, *x));
        let levels = stacks
            .iter()
            .map(|(_, _, z, _)| *z)
            .chain(rooms.iter().map(|r| r.z));
        let min_z = levels.clone().min().unwrap_or(0).min(0);
        let ground = terrain.cell(&land, &veg, x0, y0, seed, attr(job, "seams") == "1");
        let mut max_z = levels.max().unwrap_or(0);
        // A cell containing only basement rooms can have no level zero at all.
        if max_z < 0
            && ground.iter().any(|(_, tiles)| {
                tiles
                    .chunks_exact(258)
                    .skip(1)
                    .take(256)
                    .any(|row| row[1..257].iter().any(|id| *id != 0))
            })
        {
            max_z = 0;
        }
        if min_z < -32 || max_z > 31 {
            return Err(format!(
                "cell {cx},{cy}: levels {min_z} to {max_z} outside Build 42 range"
            ));
        }
        let mut cell = Cell::empty((max_z - min_z + 1) as usize);
        let mut base = HashMap::new();
        let mut names = Vec::new();
        let mut ids = HashMap::<String, u32>::new();
        let mut intern = |s: &str| -> u32 {
            if let Some(&id) = ids.get(s) {
                return id;
            }
            let id = names.len() as u32;
            names.push(s.to_owned());
            ids.insert(s.to_owned(), id);
            id
        };
        for (wx, wy, z, stack) in stacks {
            let (x, y) = ((wx - x0) as usize, (wy - y0) as usize);
            if z == 0 {
                base.insert((x, y), stack);
            } else {
                let tiles = stack.iter().map(|(_, t)| intern(t)).collect();
                cell.set(
                    (z - min_z) as usize,
                    x,
                    y,
                    Some(Square {
                        room: u32::MAX,
                        tiles,
                    }),
                );
            }
        }
        for y in 0..256 {
            for x in 0..256 {
                let j = (y + 1) * 258 + x + 1;
                let bt = base.get(&(x, y));
                let mut tiles = Vec::new();
                if !interiors.contains(&(x0 + x as i32, y0 + y as i32)) {
                    let fenced =
                        bt.is_some_and(|v| v.iter().any(|(_, t)| t.starts_with("fencing_")));
                    for (furn, arr) in &ground {
                        let id = arr[j];
                        if id != 0 && !(fenced && *furn) {
                            tiles.push(intern(&terrain.names[id as usize]));
                        }
                    }
                }
                if let Some(bt) = bt {
                    tiles.extend(bt.iter().map(|(_, t)| intern(t)));
                }
                if !tiles.is_empty() {
                    cell.set(
                        (-min_z) as usize,
                        x,
                        y,
                        Some(Square {
                            room: u32::MAX,
                            tiles,
                        }),
                    );
                }
            }
        }
        cell.names = names;
        let data = KCell {
            cell_x: cx.try_into().map_err(|_| "negative cell x")?,
            cell_y: cy.try_into().map_err(|_| "negative cell y")?,
            min_z,
            rooms,
            buildings,
            zombie: None,
            squares: cell,
        }
        .write()?;
        fs::write(out.join(format!("cell_{cx}_{cy}.kcell")), data).map_err(|e| e.to_string())?;
    }
    if let Some(f) = job.attribute("footprints") {
        let mut report = String::from("<footprints>");
        for (n, cols) in footprints {
            report.push_str(&format!("<lot name=\"{}\">", xml(n)));
            for c in cols {
                report.push_str(&format!("{c} "));
            }
            report.push_str("</lot>");
        }
        report.push_str("</footprints>");
        fs::write(f, report).map_err(|e| e.to_string())?;
    }
    Ok(())
}
