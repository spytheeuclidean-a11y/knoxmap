use super::building::{Building, Tile};
use super::{attr, number, Node, Point};
use std::collections::HashMap;
type Surface = HashMap<Point, Tile>;
type Pitched = HashMap<Point, Vec<Tile>>;
fn rect(o: Node) -> Result<(i32, i32, i32, i32), String> {
    Ok((
        number(o, "x")?,
        number(o, "y")?,
        number(o, "width")?,
        number(o, "height")?,
    ))
}
fn pitched(b: &Building, o: Node) -> Result<Pitched, String> {
    let (x, y, w, h) = rect(o)?;
    let kind = attr(o, "RoofType");
    let mut depth = attr(o, "Depth");
    let slopes = b.ref_id(o, "SlopeTiles", "RoofSlope");
    let caps = b.ref_id(o, "CapTiles", "RoofCap");
    let mut top = Surface::new();
    let mut end = Surface::new();
    if matches!(kind, "PeakWE" | "PeakNS" | "Peak30WE" | "Peak30NS") {
        let we = kind.ends_with("WE");
        let low = kind.starts_with("Peak30");
        let span = if we { w } else { h };
        let mut across = if we { h } else { w };
        let at = |along, cross| {
            if we {
                (x + along, y + cross)
            } else {
                (x + cross, y + along)
            }
        };
        let side = if we { "S" } else { "E" };
        let back = if we { "N" } else { "W" };
        let cap = if we { "E" } else { "S" };
        if low {
            across = across.min(11);
        } else if depth == "Three" && (1..=5).contains(&across) {
            depth = ["Point5", "One", "OnePoint5", "Two", "TwoPoint5"][(across - 1) as usize];
        }
        let (k, ridge) = if low {
            ((across - 1) / 2, Some(""))
        } else {
            match depth {
                "Point5" => (0, Some("Pt5")),
                "One" => (1, None),
                "OnePoint5" => (1, Some("OnePt5")),
                "Two" => (2, None),
                "TwoPoint5" => (2, Some("TwoPt5")),
                "Three" => (3, None),
                _ => return Ok(HashMap::new()),
            }
        };
        for a in 0..span {
            for i in 1..=k {
                let prefix = if low { "Slope30" } else { "Slope" };
                top.insert(
                    at(a, across - i),
                    b.tile(slopes, &format!("{prefix}{side}{i}")),
                );
                if low {
                    top.insert(at(a, i - 1), b.tile(slopes, &format!("Slope30{back}{i}")));
                }
            }
            if let Some(pt) = ridge {
                let key = if low {
                    format!("Peak30{}{}", if we { "NS" } else { "WE" }, k + 1)
                } else {
                    format!("Slope{pt}{side}")
                };
                top.insert(
                    at(a, if low { k } else { across - k - 1 }),
                    b.tile(slopes, &key),
                );
            }
        }
        for (a, flag) in [
            (0, if we { "cappedW" } else { "cappedN" }),
            (span, if we { "cappedE" } else { "cappedS" }),
        ] {
            if attr(o, flag) != "true" {
                continue;
            }
            for i in 1..=k {
                let prefix = if low { "CapSlope30" } else { "Cap" };
                for (c, dir) in [
                    (i - 1, if we { "Fall" } else { "Rise" }),
                    (across - i, if we { "Rise" } else { "Fall" }),
                ] {
                    end.insert(at(a, c), b.tile(caps, &format!("{prefix}{dir}{cap}{i}")));
                }
            }
            if let Some(pt) = ridge {
                let key = if low {
                    format!("CapPeak30{cap}{}", k + 1)
                } else {
                    format!("Peak{pt}{cap}")
                };
                end.insert(at(a, k), b.tile(caps, &key));
            }
            if !low && depth == "Three" {
                for c in k..across - k {
                    end.insert(at(a, c), b.tile(caps, &format!("CapGap{cap}3")));
                }
            }
        }
    } else if kind == "Peak30Quad" && w.min(h) % 2 == 1 && w.min(h) <= 11 {
        let center = (w.min(h) - 1) / 2 + 1;
        for j in 0..h {
            for i in 0..w {
                let r = i.min(j).min(w - 1 - i).min(h - 1 - j) + 1;
                let prefix = if r == center {
                    if w == h {
                        "Peak30Quad"
                    } else if w > h {
                        "Peak30NS"
                    } else {
                        "Peak30WE"
                    }
                } else {
                    match (j == r - 1, j == h - r, i == r - 1, i == w - r) {
                        (true, _, true, _) => "OuterSlope30NW",
                        (true, _, _, true) => "OuterSlope30NE",
                        (_, true, true, _) => "OuterSlope30SW",
                        (_, true, _, true) => "OuterSlope30SE",
                        (true, _, _, _) => "Slope30N",
                        (_, true, _, _) => "Slope30S",
                        (_, _, true, _) => "Slope30W",
                        _ => "Slope30E",
                    }
                };
                top.insert((x + i, y + j), b.tile(slopes, &format!("{prefix}{r}")));
            }
        }
    }
    let mut result = Pitched::new();
    for m in [end, top] {
        for (p, t) in m {
            if !t.is_empty() {
                result.entry(p).or_default().push(t);
            }
        }
    }
    Ok(result)
}
pub fn upper(b: &Building, z: usize) -> Result<(Surface, Pitched), String> {
    let mut flat = Surface::new();
    let mut roofs = Pitched::new();
    if z > 0 {
        for y in 0..b.h {
            for x in 0..b.w {
                let r = b.room(z - 1, x, y);
                if r > 0 && b.room(z, x, y) == 0 {
                    let t = b.tile(attr(b.rooms[r - 1], "Ceiling"), "Ceiling");
                    if !t.is_empty() {
                        flat.insert((x, y), t);
                    }
                }
            }
        }
        for &o in &b.floors[z - 1].objects {
            if attr(o, "type") != "roof" {
                continue;
            }
            let kind = attr(o, "RoofType");
            let (mut x, mut y, mut w, mut h) = rect(o)?;
            let key = match kind {
                "FlatTop" => "West1",
                "PeakWE" if attr(o, "Depth") == "Three" => {
                    y += 3;
                    h -= 6;
                    "West1"
                }
                "PeakNS" if attr(o, "Depth") == "Three" => {
                    x += 3;
                    w -= 6;
                    "North1"
                }
                _ => continue,
            };
            let id = b.ref_id(o, "TopTiles", "RoofTop");
            let mut t = b.tile(id, key);
            if t.is_empty() {
                t = b.first(id);
            }
            if !t.is_empty() {
                for j in y..y + h {
                    for i in x..x + w {
                        flat.insert((i, j), t.clone());
                    }
                }
            }
        }
    }
    let mut wings = Vec::new();
    for &o in &b.floors[z].objects {
        match attr(o, "type") {
            "hole" => {
                flat.remove(&(number(o, "x")?, number(o, "y")?));
            }
            "roof" if attr(o, "RoofType") != "FlatTop" => {
                for (p, v) in pitched(b, o)? {
                    roofs.entry(p).or_default().extend(v);
                }
                wings.push(o);
            }
            _ => {}
        }
    }
    for &we in wings.iter().filter(|o| attr(**o, "RoofType") == "Peak30WE") {
        let (x, y, w, h) = rect(we)?;
        let h = h.min(11);
        for &ns in wings.iter().filter(|o| attr(**o, "RoofType") == "Peak30NS") {
            let (nx, ny, nw, nh) = rect(ns)?;
            let nw = nw.min(11);
            if nx >= x + w || nx + nw <= x {
                continue;
            }
            let (row, dir) = if ny == y + h {
                (y + h - 1, "S")
            } else if ny + nh == y {
                (y, "N")
            } else {
                continue;
            };
            for (col, edge, ok) in [(nx - 1, "E", nx > x), (nx + nw, "W", nx + nw < x + w)] {
                let t = b.tile(
                    b.ref_id(we, "SlopeTiles", "RoofSlope"),
                    &format!("InnerSlope30{dir}{edge}1"),
                );
                if ok && !t.is_empty() {
                    roofs.insert((col, row), vec![t]);
                }
            }
        }
    }
    Ok((flat, roofs))
}
