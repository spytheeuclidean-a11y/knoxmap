//! TBX tiles in BuildingEd draw order. Preserve the channel until all lots
//! have been composed: two walls meeting at a corner can share a square.
use super::{attr, children, number, Node, Point};
use std::collections::{HashMap, HashSet};
use std::rc::Rc;

pub type Tile = Rc<str>;
pub type Stack = Vec<(&'static str, Tile)>;
pub type Layers = HashMap<Point, Stack>;
type Entry = Vec<(String, Tile)>;

pub fn tile_name(s: &str) -> String {
    if let Some((prefix, digits)) = s.rsplit_once('_') {
        if !digits.is_empty() && digits.bytes().all(|b| b.is_ascii_digit()) {
            let short = digits.trim_start_matches('0');
            return format!("{prefix}_{}", if short.is_empty() { "0" } else { short });
        }
    }
    s.to_owned()
}

pub struct Floor<'a> {
    pub rooms: Vec<usize>,
    pub objects: Vec<Node<'a>>,
    painted: Vec<(Point, Tile)>,
}
pub struct Building<'a> {
    pub root: Node<'a>,
    pub w: i32,
    pub h: i32,
    pub rooms: Vec<Node<'a>>,
    pub floors: Vec<Floor<'a>>,
    entries: Vec<Entry>,
    furniture: Vec<Node<'a>>,
}
impl<'a> Building<'a> {
    pub fn parse(root: Node<'a>, rooms_only: bool) -> Result<Self, String> {
        let (w, h) = (number(root, "width")?, number(root, "height")?);
        let cells = w
            .checked_mul(h)
            .filter(|_| w > 0 && h > 0)
            .ok_or("invalid TBX dimensions")? as usize;
        let rooms: Vec<_> = children(root, "room").collect();
        let mut entries = vec![vec![]];
        let mut user_tiles: Vec<Tile> = vec!["".into()];
        if !rooms_only {
            for e in children(root, "tile_entry") {
                entries.push(
                    e.children()
                        .filter(|n| n.is_element())
                        .map(|t| {
                            (
                                attr(t, "enum").to_owned(),
                                Tile::from(tile_name(attr(t, "tile"))),
                            )
                        })
                        .collect(),
                );
            }
            for u in children(root, "user_tiles") {
                user_tiles.extend(
                    u.children()
                        .filter(|n| n.is_element())
                        .map(|t| Tile::from(tile_name(attr(t, "tile")))),
                );
            }
        }
        let mut floors = Vec::new();
        for f in children(root, "floor") {
            let parse_grid = |node: Node| -> Result<Vec<i32>, String> {
                node.text()
                    .unwrap_or("")
                    .split(|c: char| c == ',' || c.is_whitespace())
                    .filter(|s| !s.is_empty())
                    .map(|s| s.parse().map_err(|_| format!("invalid grid value {s}")))
                    .collect()
            };
            let grid = parse_grid(
                children(f, "rooms")
                    .next()
                    .ok_or("missing TBX rooms grid")?,
            )?;
            if grid.len() != cells || grid.iter().any(|&r| r < 0 || r as usize > rooms.len()) {
                return Err("invalid TBX rooms grid".into());
            }
            let mut painted = Vec::new();
            if !rooms_only {
                for t in children(f, "tiles") {
                    let grid = parse_grid(t)?;
                    let width = w as usize + 1;
                    if grid.len() != width * (h as usize + 1) {
                        return Err("invalid TBX painted grid".into());
                    }
                    for (i, v) in grid.into_iter().enumerate() {
                        if let Some(tile) = user_tiles.get(v as usize).filter(|t| !t.is_empty()) {
                            painted.push((((i % width) as i32, (i / width) as i32), tile.clone()));
                        }
                    }
                }
            }
            floors.push(Floor {
                rooms: grid.into_iter().map(|v| v as usize).collect(),
                objects: if rooms_only {
                    vec![]
                } else {
                    children(f, "object").collect()
                },
                painted,
            });
        }
        Ok(Self {
            root,
            w,
            h,
            rooms,
            floors,
            entries,
            furniture: children(root, "furniture").collect(),
        })
    }
    fn entry(&self, id: &str) -> &Entry {
        id.parse::<usize>()
            .ok()
            .and_then(|n| self.entries.get(n))
            .unwrap_or(&self.entries[0])
    }
    pub fn tile(&self, id: &str, key: &str) -> Tile {
        self.entry(id)
            .iter()
            .find(|(k, _)| k == key)
            .map(|(_, v)| v.clone())
            .unwrap_or_default()
    }
    pub fn first(&self, id: &str) -> Tile {
        self.entry(id)
            .first()
            .map(|(_, v)| v.clone())
            .unwrap_or_default()
    }
    pub fn room(&self, z: usize, x: i32, y: i32) -> usize {
        if x >= 0 && y >= 0 && x < self.w && y < self.h {
            self.floors[z].rooms[(y * self.w + x) as usize]
        } else {
            0
        }
    }
    pub fn ref_id(&self, o: Node<'a>, k: &str, default: &str) -> &'a str {
        o.attribute(k).unwrap_or(attr(self.root, default))
    }
}
fn pos(o: Node) -> Result<Point, String> {
    Ok((number(o, "x")?, number(o, "y")?))
}
fn stairs(o: Node) -> Result<[Point; 3], String> {
    let (x, y) = pos(o)?;
    Ok([1, 2, 3].map(|i| {
        if attr(o, "dir") == "N" {
            (x, y + i)
        } else {
            (x + i, y)
        }
    }))
}
fn variant(tile: &str) -> i32 {
    let Some((sheet, n)) = tile.rsplit_once('_') else {
        return 0;
    };
    let Ok(n) = n.parse::<i32>() else { return 0 };
    match sheet {
        "fixtures_windows_white"
        | "fixtures_windows_metal"
        | "fixtures_windows_wood"
        | "fixtures_windows_church" => n / 2 + 1,
        "fixtures_windows_01" => match n {
            40 | 42 | 48 | 50 => 17,
            41 | 43 | 49 | 51 => 18,
            _ => 0,
        },
        _ => 0,
    }
}
fn push(layers: &mut Layers, p: Point, channel: &'static str, tile: Tile) {
    if !tile.is_empty() {
        layers.entry(p).or_default().push((channel, tile));
    }
}
pub fn level(b: &Building, z: usize) -> Result<Layers, String> {
    let f = &b.floors[z];
    let room = |x, y| b.room(z, x, y);
    let ext = attr(b.root, "ExteriorWall");
    let trim = attr(b.root, "ExteriorWallTrim");
    let grime = if z == 0 {
        attr(b.root, "GrimeWall")
    } else {
        ""
    };
    let mut custom = HashMap::new();
    let mut ends = HashMap::new();
    let mut holes = HashSet::new();
    let mut furnishings = Vec::new();
    let mut wall_furn: HashMap<Point, Vec<(&str, Tile)>> = HashMap::new();
    let mut trim_ids = vec![trim];
    trim_ids.extend(b.rooms.iter().map(|r| attr(*r, "InteriorWallTrim")));
    for &o in &f.objects {
        match attr(o, "type") {
            "wall" => {
                let (x, y) = pos(o)?;
                let horizontal = o.attribute("dir").unwrap_or("W") == "W";
                let len = o
                    .attribute("length")
                    .unwrap_or("1")
                    .parse::<i32>()
                    .map_err(|_| "invalid wall length")?;
                let at = |i| if horizontal { (x + i, y) } else { (x, y + i) };
                for i in 0..len {
                    custom.insert((at(i), if horizontal { "North" } else { "West" }), o);
                }
                ends.insert(at(len), o);
                trim_ids.extend([attr(o, "ExteriorTrim"), attr(o, "InteriorTrim")]);
            }
            "hole" => {
                holes.insert(pos(o)?);
            }
            "furniture" => {
                let Some(def) = attr(o, "FurnitureTiles")
                    .parse::<usize>()
                    .ok()
                    .and_then(|i| b.furniture.get(i))
                else {
                    continue;
                };
                let layer = attr(*def, "layer");
                let orient = o.attribute("orient").unwrap_or("N");
                let (x, y) = pos(o)?;
                if let Some(entry) = children(*def, "entry")
                    .filter(|e| attr(*e, "orient") == orient)
                    .last()
                {
                    for (i, t) in children(entry, "tile").enumerate() {
                        let p = (x + number(t, "x")?, y + number(t, "y")?);
                        let tile = Tile::from(tile_name(attr(t, "name")));
                        if layer == "Walls" {
                            wall_furn.entry(p).or_default().push((orient, tile));
                        } else {
                            let rank = match layer {
                                "FloorFurniture" => 0,
                                "Roof" => 6,
                                "WallFurniture" if matches!(orient, "N" | "W") => 1,
                                "WallFurniture" => 5,
                                _ if i == 0 => 2,
                                _ => 3,
                            };
                            furnishings.push((rank, p, tile));
                        }
                    }
                }
            }
            _ => {}
        }
    }
    if z > 0 {
        for &o in &b.floors[z - 1].objects {
            if attr(o, "type") == "stairs" {
                holes.extend(stairs(o)?);
            }
        }
    }
    let west = |x, y| custom.contains_key(&((x, y), "West")) || room(x - 1, y) != room(x, y);
    let north = |x, y| custom.contains_key(&((x, y), "North")) || room(x, y - 1) != room(x, y);
    let outside = |w: Tile, t: Tile, g: Tile| if z == 0 { vec![w, t, g] } else { vec![w, g] };
    let wall = |p: Point, k: &str, fallback: &str, end: bool| {
        let r = room(p.0, p.1);
        let obj = if k == "SouthEast" {
            if end {
                ends.get(&p)
            } else {
                None
            }
        } else {
            custom.get(&(
                p,
                if k.starts_with("North") {
                    "North"
                } else {
                    "West"
                },
            ))
        };
        let (id, tr) = if let Some(o) = obj {
            let id = attr(*o, if r > 0 { "InteriorTile" } else { "Tile" });
            if b.entry(id).is_empty() {
                return vec![];
            }
            (
                id,
                attr(
                    *o,
                    if r > 0 {
                        "InteriorTrim"
                    } else {
                        "ExteriorTrim"
                    },
                ),
            )
        } else if r > 0 {
            (
                attr(b.rooms[r - 1], "InteriorWall"),
                attr(b.rooms[r - 1], "InteriorWallTrim"),
            )
        } else {
            return outside(b.tile(ext, k), b.tile(trim, k), b.tile(grime, k));
        };
        let key = if b.tile(id, k).is_empty() {
            fallback
        } else {
            k
        };
        let mut v = vec![b.tile(id, key)];
        if obj.is_some() || !b.entry(tr).is_empty() {
            v.push(b.tile(tr, key));
        }
        if obj.is_some() && r == 0 {
            v.push(b.tile(grime, k));
        }
        v
    };
    let mut out = Layers::new();
    let mut kinds = HashMap::new();
    let mut walls: HashMap<Point, Vec<Tile>> = HashMap::new();
    for y in 0..=b.h {
        for x in 0..=b.w {
            let p = (x, y);
            let r = room(x, y);
            if r > 0 && !holes.contains(&p) {
                push(
                    &mut out,
                    p,
                    "floor",
                    b.tile(attr(b.rooms[r - 1], "Floor"), "Floor"),
                );
            }
            let mut w = west(x, y);
            let mut n = north(x, y);
            for (d, _) in wall_furn.get(&p).into_iter().flatten() {
                if *d == "W" {
                    w = false;
                }
                if *d == "N" {
                    n = false;
                }
            }
            let k = match (w, n) {
                (true, true) => "NorthWest",
                (true, false) => "West",
                (false, true) => "North",
                _ => "SouthEast",
            };
            let post = !wall_furn.contains_key(&p) && west(x, y - 1) && north(x - 1, y);
            if w || n || post || ends.contains_key(&p) {
                kinds.insert(p, k);
                let mut v = wall(p, k, "", !post);
                if k == "NorthWest"
                    && (custom.contains_key(&(p, "North")) || custom.contains_key(&(p, "West")))
                {
                    let (n, o) = if custom.contains_key(&(p, "North")) {
                        ("North", "West")
                    } else {
                        ("West", "North")
                    };
                    v = wall(p, n, "", false);
                    let at = v.len().min(1);
                    v.splice(at..at, wall(p, o, "", false));
                }
                walls.insert(p, v);
            }
        }
    }
    for (p, v) in wall_furn {
        walls
            .entry(p)
            .or_default()
            .extend(v.into_iter().map(|(_, t)| t));
    }
    let (ceilings, roofs) = super::roof::upper(b, z)?;
    for (p, t) in ceilings {
        push(&mut out, p, "floor", t);
    }
    let mut extra = Layers::new();
    let mut curtains_nw = Layers::new();
    let mut curtains_se = Layers::new();
    let mut openings = Vec::new();
    let mut lookup = HashMap::new();
    for &o in &f.objects {
        if matches!(attr(o, "type"), "door" | "window") {
            let key = (
                attr(o, "type"),
                attr(o, "x"),
                attr(o, "y"),
                o.attribute("dir").unwrap_or("N"),
            );
            let i = *lookup.entry(key).or_insert(openings.len());
            if i == openings.len() {
                openings.push(o)
            } else {
                openings[i] = o
            }
        }
    }
    let direction = |o: Node| {
        if o.attribute("dir").unwrap_or("N") == "N" {
            "North"
        } else {
            "West"
        }
    };
    let mut by_edge = HashMap::new();
    for &o in &openings {
        by_edge.insert((pos(o)?, direction(o)), o);
    }
    let opening_wall = |p: Point, d: &str| {
        let Some(&o) = by_edge.get(&(p, d)) else {
            return wall(p, d, "", false);
        };
        if attr(o, "type") == "door" {
            return wall(p, &format!("{d}Door"), "", false);
        }
        let plain = format!("{d}Window");
        let v = variant(&b.tile(b.ref_id(o, "Tile", "Window"), d));
        let key = if v > 0 {
            format!("{plain}{v}")
        } else {
            plain.clone()
        };
        if room(p.0, p.1) > 0 {
            return wall(p, &key, &plain, false);
        }
        let overlay = |id| {
            [key.as_str(), &plain, d]
                .iter()
                .map(|k| b.tile(id, k))
                .find(|t| !t.is_empty())
                .unwrap_or_default()
        };
        outside(
            if b.tile(ext, &key).is_empty() {
                b.tile(ext, &plain)
            } else {
                b.tile(ext, &key)
            },
            overlay(trim),
            overlay(grime),
        )
    };
    for o in openings {
        let p = pos(o)?;
        let (x, y) = p;
        let Some(&kind) = kinds.get(&p) else { continue };
        let d = direction(o);
        let r = room(x, y);
        let mut parts = if attr(o, "type") == "door" {
            wall(p, &format!("{d}Door"), "", false)
        } else {
            opening_wall(p, d)
        };
        if kind == "NorthWest" {
            let mut other = opening_wall(p, if d == "North" { "West" } else { "North" });
            if r == 0 && parts.len() == 3 && other.len() == 3 {
                other.splice(2..2, parts);
            } else {
                other.append(&mut parts);
            }
            parts = other;
        }
        walls.insert(p, parts);
        if attr(o, "type") == "door" {
            for (k, default) in [("FrameTile", "DoorFrame"), ("Tile", "Door")] {
                push(
                    &mut extra,
                    p,
                    "openings",
                    b.tile(b.ref_id(o, k, default), d),
                );
            }
            continue;
        }
        let sh = attr(o, "ShuttersTile");
        let (a, c) = if d == "North" {
            ("NorthLeft", "NorthRight")
        } else {
            ("WestAbove", "WestBelow")
        };
        if r == 0 {
            for k in [a, c] {
                push(&mut extra, p, "openings", b.tile(sh, k));
            }
        }
        push(
            &mut extra,
            p,
            "openings",
            b.tile(b.ref_id(o, "Tile", "Window"), d),
        );
        let cur = attr(o, "CurtainsTile");
        if r > 0 {
            push(&mut curtains_nw, p, "curtains_nw", b.tile(cur, d));
        } else {
            let (q, key) = if d == "North" {
                ((x, y - 1), "South")
            } else {
                ((x - 1, y), "East")
            };
            push(&mut curtains_se, q, "curtains_se", b.tile(cur, key));
            for (delta, k) in [(-1, a), (1, c)] {
                let (qx, qy) = if d == "North" {
                    (x + delta, y)
                } else {
                    (x, y + delta)
                };
                if qx >= 0 && qx <= b.w && qy >= 0 && qy <= b.h && room(qx, qy) == 0 {
                    push(&mut extra, (qx, qy), "openings", b.tile(sh, k));
                }
            }
        }
    }
    let trim_names: HashSet<_> = trim_ids
        .iter()
        .flat_map(|id| b.entry(id).iter().map(|(_, v)| v))
        .collect();
    let north_trim: HashSet<_> = b
        .entries
        .iter()
        .flatten()
        .filter(|(k, _)| k == "SouthEast" || (k.starts_with("North") && k != "NorthWest"))
        .map(|(_, v)| v)
        .collect();
    let append = |a: &mut Layers, other: Layers| {
        for (p, v) in other {
            a.entry(p).or_default().extend(v)
        }
    };
    let furniture = |a: &mut Layers, rank, ch| {
        for (i, p, t) in &furnishings {
            if *i == rank {
                push(a, *p, ch, t.clone());
            }
        }
    };
    furniture(&mut out, 0, "floor_furniture");
    for (p, v) in walls {
        for t in v {
            let channel = if trim_names.contains(&t) {
                if north_trim.contains(&t) {
                    "wall_trim_north"
                } else {
                    "wall_trim_west"
                }
            } else if b.entry(grime).iter().any(|(_, v)| v == &t) {
                if b.entry(grime)
                    .iter()
                    .any(|(k, v)| v == &t && k.starts_with("North") && k != "NorthWest")
                {
                    "wall_grime_north"
                } else {
                    "wall_grime_west"
                }
            } else {
                match kinds.get(&p).copied() {
                    Some("West") => "walls_west",
                    Some("North") => "walls_north",
                    Some("SouthEast") => "walls_se",
                    _ => "walls",
                }
            };
            push(&mut out, p, channel, t);
        }
    }
    furniture(&mut out, 1, "wall_furniture_nw");
    for (p, t) in &f.painted {
        push(&mut out, *p, "painted", t.clone());
    }
    append(&mut out, extra);
    append(&mut out, curtains_nw);
    for &o in &f.objects {
        if attr(o, "type") == "stairs" {
            let d = if attr(o, "dir") == "N" {
                "North"
            } else {
                "West"
            };
            for (i, p) in stairs(o)?.into_iter().enumerate() {
                push(
                    &mut out,
                    p,
                    "stairs",
                    b.tile(b.ref_id(o, "Tile", "Stairs"), &format!("{d}{}", 3 - i)),
                );
            }
        }
    }
    furniture(&mut out, 2, "furniture");
    furniture(&mut out, 3, "furniture");
    append(&mut out, curtains_se);
    furniture(&mut out, 5, "wall_furniture_se");
    for (p, v) in roofs {
        for t in v {
            push(&mut out, p, "roof", t);
        }
    }
    furniture(&mut out, 6, "roof_furniture");
    Ok(out)
}

fn structure(t: &str) -> bool {
    [
        "fencing_",
        "fixtures_doors_fences",
        "walls_",
        "fixtures_railings",
    ]
    .iter()
    .any(|p| t.starts_with(p))
        || t.strip_prefix("vegetation_ornamental_01_")
            .is_some_and(|s| {
                matches!(
                    s,
                    "0" | "1"
                        | "2"
                        | "4"
                        | "5"
                        | "6"
                        | "000"
                        | "001"
                        | "002"
                        | "004"
                        | "005"
                        | "006"
                )
            })
}
pub fn compose(old: &mut Stack, mut new: Stack, room: bool) {
    if room {
        *old = new;
        return;
    }
    if new.iter().any(|(c, _)| *c == "floor") {
        old.clear();
    } else if old.iter().any(|(c, _)| *c == "floor") {
        for (d, tr, gr) in [
            ("walls_west", "wall_trim_west", "wall_grime_west"),
            ("walls_north", "wall_trim_north", "wall_grime_north"),
        ] {
            if old.iter().any(|(c, _)| *c == d) {
                new.retain(|(c, _)| *c != d && *c != "walls_se" && *c != tr && *c != gr);
            }
        }
    }
    let walled = new.iter().any(|(_, t)| structure(t));
    old.retain(|(c, t)| {
        (!walled && structure(t))
            || !new.iter().any(|(n, _)| {
                n == c
                    || match *n {
                        "walls" => matches!(*c, "walls_west" | "walls_north" | "walls_se"),
                        "walls_west" | "walls_north" => matches!(*c, "walls" | "walls_se"),
                        _ => false,
                    }
            })
    });
    let kept = old.len();
    for item in new {
        if !old[..kept].contains(&item) {
            old.push(item);
        }
    }
}
pub fn finish(stack: &mut Stack) {
    if stack.iter().any(|(_, t)| structure(t)) {
        stack.retain(|(_, t)| {
            structure(t)
                || ![
                    "lighting_outdoor",
                    "e_",
                    "f_bushes",
                    "vegetation_",
                    "d_generic",
                    "d_plants",
                ]
                .iter()
                .any(|p| t.starts_with(p))
        });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_later_lot_keeps_perpendicular_walls_and_skips_yard_props_on_fences() {
        let mut square = vec![("walls_north", Tile::from("walls_n_1"))];
        compose(
            &mut square,
            vec![("walls_west", Tile::from("walls_w_2"))],
            false,
        );
        assert_eq!(square.len(), 2);
        compose(
            &mut square,
            vec![("painted", Tile::from("fencing_01_0"))],
            false,
        );
        compose(
            &mut square,
            vec![("painted", Tile::from("lighting_outdoor_01_2"))],
            false,
        );
        finish(&mut square);
        assert_eq!(
            square.iter().map(|(_, t)| t.as_ref()).collect::<Vec<_>>(),
            ["walls_n_1", "walls_w_2", "fencing_01_0"]
        );
        compose(&mut square, vec![("floor", Tile::from("floor_1"))], true);
        assert_eq!(square.len(), 1);
    }
}
