use super::building::Building;
use super::{attr, children, lot_path, number, xml, Node, Point};
use std::{
    collections::{BTreeMap, HashMap},
    fs,
    io::{BufWriter, Write},
    path::Path,
};
struct Lot {
    x: i32,
    y: i32,
    base: i32,
    w: i32,
    h: i32,
    grids: Vec<Vec<u32>>,
    names: Vec<String>,
}
// Per-level occupancy, allocated in blocks so a few distant lots don't cost
// a dense array spanning the whole city. Zero is empty, lot indexes start at 1.
struct Owners(HashMap<Point, Box<[u32]>>);
impl Owners {
    fn key(x: i32, y: i32) -> (Point, usize) {
        (
            (x.div_euclid(64), y.div_euclid(64)),
            (y.rem_euclid(64) * 64 + x.rem_euclid(64)) as usize,
        )
    }
    fn set(&mut self, x: i32, y: i32, id: u32) {
        let (k, i) = Self::key(x, y);
        self.0
            .entry(k)
            .or_insert_with(|| vec![0; 4096].into_boxed_slice())[i] = id;
    }
    fn get(&self, x: i32, y: i32) -> u32 {
        let (k, i) = Self::key(x, y);
        self.0.get(&k).map_or(0, |v| v[i])
    }
}
fn root(parent: &mut [usize], mut i: usize) -> usize {
    while i != parent[i] {
        parent[i] = parent[parent[i]];
        i = parent[i];
    }
    i
}
pub fn prepare(job: Node, project: &Path, out: &Path) -> Result<(), String> {
    let mut lots = Vec::new();
    for lot in children(job, "lot") {
        let file = lot_path(project, attr(lot, "name"))?;
        let data = fs::read_to_string(&file).map_err(|e| format!("{}: {e}", file.display()))?;
        let doc = roxmltree::Document::parse(&data).map_err(|e| e.to_string())?;
        let b = Building::parse(doc.root_element(), true)?;
        lots.push(Lot {
            x: number(lot, "x")?,
            y: number(lot, "y")?,
            base: number(lot, "z")?,
            w: b.w,
            h: b.h,
            grids: b
                .floors
                .into_iter()
                .map(|f| f.rooms.into_iter().map(|i| i as u32).collect())
                .collect(),
            names: b
                .rooms
                .iter()
                .map(|r| attr(*r, "Name").to_owned())
                .collect(),
        });
    }
    let mut order: Vec<_> = (0..lots.len()).collect();
    order.sort_by_key(|&i| (lots[i].y.div_euclid(300), lots[i].x.div_euclid(300)));
    let mut levels = BTreeMap::<i32, Vec<(usize, usize)>>::new();
    for &i in &order {
        for z in 0..lots[i].grids.len() {
            levels
                .entry(lots[i].base + z as i32)
                .or_default()
                .push((i, z));
        }
    }
    let mut parts = vec![BTreeMap::<(i32, u32), Vec<[i32; 4]>>::new(); lots.len()];
    let mut parent: Vec<_> = (0..lots.len()).collect();
    for (level, here) in levels {
        let mut owners = Owners(HashMap::new());
        for &(i, z) in &here {
            let b = &lots[i];
            for (n, &r) in b.grids[z].iter().enumerate() {
                if r > 0 {
                    owners.set(b.x + n as i32 % b.w, b.y + n as i32 / b.w, i as u32 + 1);
                }
            }
        }
        for (i, z) in here {
            let b = &lots[i];
            let mut grid = b.grids[z].clone();
            let w = b.w as usize;
            let h = b.h as usize;
            for (n, r) in grid.iter_mut().enumerate() {
                if *r == 0 {
                    continue;
                }
                let (x, y) = (b.x + (n % w) as i32, b.y + (n / w) as i32);
                if owners.get(x, y) != i as u32 + 1 {
                    *r = 0;
                    continue;
                }
                for (dx, dy) in [(1, 0), (0, 1), (1, 1), (1, -1)] {
                    let j = owners.get(x + dx, y + dy);
                    if j != 0 && j != i as u32 + 1 {
                        let (a, c) = (root(&mut parent, i), root(&mut parent, j as usize - 1));
                        parent[a] = c;
                    }
                }
            }
            for y in 0..h {
                for x in 0..w {
                    let rid = grid[y * w + x];
                    if rid == 0 {
                        continue;
                    }
                    let mut end = x + 1;
                    while end < w && grid[y * w + end] == rid {
                        end += 1;
                    }
                    let mut bottom = y + 1;
                    while bottom < h {
                        let row = &grid[bottom * w..(bottom + 1) * w];
                        if x > 0 && row[x - 1] == rid
                            || end < w && row[end] == rid
                            || row[x..end].iter().any(|&r| r != rid)
                        {
                            break;
                        }
                        bottom += 1;
                    }
                    for j in y..bottom {
                        grid[j * w + x..j * w + end].fill(0);
                    }
                    parts[i].entry((level, rid)).or_default().push([
                        b.x + x as i32,
                        b.y + y as i32,
                        (end - x) as i32,
                        (bottom - y) as i32,
                    ]);
                }
            }
        }
    }
    let mut groups = Vec::<Vec<usize>>::new();
    let mut index = HashMap::new();
    for i in order {
        let g = *index.entry(root(&mut parent, i)).or_insert_with(|| {
            groups.push(vec![]);
            groups.len() - 1
        });
        groups[g].push(i);
    }
    let mut dest = BufWriter::new(fs::File::create(out).map_err(|e| e.to_string())?);
    (|| -> std::io::Result<()> {
        writeln!(dest, "<tables>")?;
        for b in &lots {
            writeln!(dest, "<size w=\"{}\" h=\"{}\"/>", b.w, b.h)?;
        }
        for group in groups {
            if group.iter().all(|i| parts[*i].is_empty()) {
                continue;
            }
            let first = &lots[group[0]];
            writeln!(dest, "<building x=\"{}\" y=\"{}\">", first.x, first.y)?;
            for i in group {
                for ((z, r), rects) in &parts[i] {
                    write!(
                        dest,
                        "<room name=\"{}\" z=\"{z}\">",
                        xml(&lots[i].names[*r as usize - 1])
                    )?;
                    for [x, y, w, h] in rects {
                        write!(dest, "{x} {y} {w} {h} ")?;
                    }
                    writeln!(dest, "</room>")?;
                }
            }
            writeln!(dest, "</building>")?;
        }
        writeln!(dest, "</tables>")?;
        dest.flush()
    })()
    .map_err(|e| e.to_string())
}
