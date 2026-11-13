//! Isometric lot renderer (`knoxlots render` and `knoxlots tile-list`).
//!
//! Reads compiled `.lotheader` and `.lotpack` files in parallel across cells
//! and composites pre-decoded sprites onto an RGB framebuffer in painter's
//! order (`z`, then `dx + dy`, then `dx`), matching `tools/render_lots.py`.

use crate::header::Header;
use crate::pack::{Pack, Rec};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::thread;

const CELL: i32 = 256;
const CHUNKS: i32 = 32;
const CHUNK: i32 = 8;
const LEVEL_PX: f64 = 96.0;

#[derive(Clone)]
pub struct Sprite {
    pub ox: i32,
    pub oy: i32,
    pub sw: i32,
    pub sh: i32,
    pub opaque: bool,
    pub rgba: Vec<u8>,
}

#[derive(Clone, Copy)]
struct Square {
    diag: i32,
    dx: i32,
    dy: i32,
    start: u32,
    len: u16,
}

fn read_sprites(path: &Path) -> Result<(Vec<Sprite>, HashMap<String, u32>), String> {
    let data = fs::read(path).map_err(|e| format!("{}: {e}", path.display()))?;
    if data.len() < 8 || &data[0..4] != b"SPR1" {
        return Err("invalid sprite bank header".into());
    }
    let count = u32::from_le_bytes([data[4], data[5], data[6], data[7]]) as usize;
    let mut pos = 8usize;
    let mut sprites = Vec::with_capacity(count);
    let mut by_name = HashMap::with_capacity(count * 2);
    for idx in 0..count {
        if pos + 2 > data.len() {
            return Err("truncated sprite name length".into());
        }
        let nlen = u16::from_le_bytes([data[pos], data[pos + 1]]) as usize;
        pos += 2;
        if pos + nlen + 9 > data.len() {
            return Err("truncated sprite metadata".into());
        }
        let name = std::str::from_utf8(&data[pos..pos + nlen])
            .map_err(|_| "invalid sprite name utf8")?
            .to_string();
        pos += nlen;
        let ox = i16::from_le_bytes([data[pos], data[pos + 1]]) as i32;
        let oy = i16::from_le_bytes([data[pos + 2], data[pos + 3]]) as i32;
        let sw = i16::from_le_bytes([data[pos + 4], data[pos + 5]]) as i32;
        let sh = i16::from_le_bytes([data[pos + 6], data[pos + 7]]) as i32;
        let opaque = data[pos + 8] != 0;
        pos += 9;
        let px_bytes = (sw.max(0) as usize) * (sh.max(0) as usize) * 4;
        if pos + px_bytes > data.len() {
            return Err("truncated sprite pixel data".into());
        }
        let rgba = data[pos..pos + px_bytes].to_vec();
        pos += px_bytes;
        by_name.insert(name, idx as u32);
        sprites.push(Sprite {
            ox,
            oy,
            sw,
            sh,
            opaque,
            rgba,
        });
    }
    Ok((sprites, by_name))
}

fn cell_coords(ox: i32, oy: i32, x: i32, y: i32, w: i32, h: i32) -> Vec<(i32, i32)> {
    let wx0 = ox + x;
    let wy0 = oy + y;
    let cx0 = wx0.div_euclid(CELL);
    let cx1 = (wx0 + w - 1).div_euclid(CELL);
    let cy0 = wy0.div_euclid(CELL);
    let cy1 = (wy0 + h - 1).div_euclid(CELL);
    let mut out = Vec::new();
    for cx in cx0..=cx1 {
        for cy in cy0..=cy1 {
            out.push((cx, cy));
        }
    }
    out
}

/// Collect every unique tile name referenced by `.lotheader` files in the box.
pub fn tile_list(
    lots_dir: &Path,
    ox: i32,
    oy: i32,
    x: i32,
    y: i32,
    w: i32,
    h: i32,
) -> Result<Vec<String>, String> {
    let coords = cell_coords(ox, oy, x, y, w, h);
    let mut seen: HashSet<String> = HashSet::new();
    for (cx, cy) in coords {
        let header_path = lots_dir.join(format!("{cx}_{cy}.lotheader"));
        let pack_path = lots_dir.join(format!("world_{cx}_{cy}.lotpack"));
        if !header_path.is_file() || !pack_path.is_file() {
            continue;
        }
        let bytes = fs::read(&header_path).map_err(|e| format!("{}: {e}", header_path.display()))?;
        let hdr = Header::parse(&bytes)?;
        for name in hdr.tiles {
            seen.insert(name);
        }
    }
    let mut out: Vec<String> = seen.into_iter().collect();
    out.sort_unstable();
    Ok(out)
}

fn collect_cell(
    lots_dir: &Path,
    cxw: i32,
    cyw: i32,
    wx0: i32,
    wy0: i32,
    w: i32,
    h: i32,
    max_level: Option<i32>,
    skip_blends: bool,
    by_name: &HashMap<String, u32>,
    out_by_z: &mut BTreeMap<i32, (Vec<Square>, Vec<u32>)>,
) -> Result<(), String> {
    let header_path = lots_dir.join(format!("{cxw}_{cyw}.lotheader"));
    let pack_path = lots_dir.join(format!("world_{cxw}_{cyw}.lotpack"));
    if !header_path.is_file() || !pack_path.is_file() {
        return Ok(());
    }
    let hbytes = fs::read(&header_path).map_err(|e| format!("{}: {e}", header_path.display()))?;
    let pbytes = fs::read(&pack_path).map_err(|e| format!("{}: {e}", pack_path.display()))?;
    let hdr = Header::parse(&hbytes)?;
    let pack = Pack::parse(&pbytes)?;

    let mut id_to_sprite: Vec<Option<u32>> = Vec::with_capacity(hdr.tiles.len());
    let mut is_blend: Vec<bool> = Vec::with_capacity(hdr.tiles.len());
    for name in &hdr.tiles {
        id_to_sprite.push(by_name.get(name).copied());
        is_blend.push(name.starts_with("blends_"));
    }

    let base_x = cxw * CELL;
    let base_y = cyw * CELL;
    let lx0 = wx0 - base_x;
    let ly0 = wy0 - base_y;
    let lx1 = wx0 + w - base_x;
    let ly1 = wy0 + h - base_y;

    for cx in 0..CHUNKS {
        let bx = cx * CHUNK;
        if bx + CHUNK <= lx0 || bx >= lx1 {
            continue;
        }
        for cy in 0..CHUNKS {
            let by = cy * CHUNK;
            if by + CHUNK <= ly0 || by >= ly1 {
                continue;
            }
            let chunk_idx = (cx * CHUNKS + cy) as usize;
            let Some(recs) = pack.chunks.get(chunk_idx) else {
                continue;
            };
            if recs.is_empty() {
                continue;
            }
            let mut rec_i = 0usize;
            let mut skip = 0u32;
            for z in hdr.min_z..=hdr.max_z {
                let z_skip = max_level.is_some_and(|ml| z > ml);
                for x in 0..CHUNK {
                    for y in 0..CHUNK {
                        if skip > 0 {
                            skip -= 1;
                            continue;
                        }
                        let Some(rec) = recs.get(rec_i) else {
                            break;
                        };
                        rec_i += 1;
                        match rec {
                            Rec::Skip(c) => {
                                skip = c.saturating_sub(1);
                            }
                            Rec::Square(vals) => {
                                if z_skip || vals.len() <= 1 {
                                    continue;
                                }
                                let sx = bx + x;
                                let sy = by + y;
                                if sx < lx0 || sx >= lx1 || sy < ly0 || sy >= ly1 {
                                    continue;
                                }
                                let dx = base_x + sx - wx0;
                                let dy = base_y + sy - wy0;
                                let entry = out_by_z.entry(z).or_insert_with(|| (Vec::new(), Vec::new()));
                                let start = entry.1.len() as u32;
                                let ids = &vals[1..];
                                for (pos_in_sq, &tid) in ids.iter().enumerate() {
                                    let tid = tid as usize;
                                    if tid >= id_to_sprite.len() {
                                        continue;
                                    }
                                    if skip_blends && !(z == 0 && pos_in_sq == 0) && is_blend[tid] {
                                        continue;
                                    }
                                    if let Some(sp_idx) = id_to_sprite[tid] {
                                        entry.1.push(sp_idx);
                                    }
                                }
                                let len = (entry.1.len() as u32 - start) as u16;
                                if len > 0 {
                                    entry.0.push(Square {
                                        diag: dx + dy,
                                        dx,
                                        dy,
                                        start,
                                        len,
                                    });
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    Ok(())
}

#[inline(always)]
fn blit_sprite(
    canvas: &mut [u8],
    cw: i32,
    ch: i32,
    px: i32,
    py: i32,
    sp: &Sprite,
) {
    let x0 = px + sp.ox;
    let y0 = py + sp.oy;
    let x1 = x0 + sp.sw;
    let y1 = y0 + sp.sh;
    if x1 <= 0 || y1 <= 0 || x0 >= cw || y0 >= ch {
        return;
    }
    let sx0 = (-x0).max(0);
    let sy0 = (-y0).max(0);
    let sx1 = sp.sw - (x1 - cw).max(0);
    let sy1 = sp.sh - (y1 - ch).max(0);
    let span_w = (sx1 - sx0) as usize;
    let sw_u = sp.sw as usize;
    let cw_u = cw as usize;

    if sp.opaque {
        for sy in sy0..sy1 {
            let cy = (y0 + sy) as usize;
            let cx = (x0 + sx0) as usize;
            let mut dst_i = (cy * cw_u + cx) * 3;
            let mut src_i = ((sy as usize) * sw_u + (sx0 as usize)) * 4;
            for _ in 0..span_w {
                canvas[dst_i] = sp.rgba[src_i];
                canvas[dst_i + 1] = sp.rgba[src_i + 1];
                canvas[dst_i + 2] = sp.rgba[src_i + 2];
                dst_i += 3;
                src_i += 4;
            }
        }
        return;
    }

    for sy in sy0..sy1 {
        let cy = (y0 + sy) as usize;
        let cx = (x0 + sx0) as usize;
        let mut dst_i = (cy * cw_u + cx) * 3;
        let mut src_i = ((sy as usize) * sw_u + (sx0 as usize)) * 4;
        for _ in 0..span_w {
            let a = sp.rgba[src_i + 3];
            if a == 255 {
                canvas[dst_i] = sp.rgba[src_i];
                canvas[dst_i + 1] = sp.rgba[src_i + 1];
                canvas[dst_i + 2] = sp.rgba[src_i + 2];
            } else if a != 0 {
                let a16 = a as u16;
                let inv = 255u16 - a16;
                let sr = sp.rgba[src_i] as u16;
                let sg = sp.rgba[src_i + 1] as u16;
                let sb = sp.rgba[src_i + 2] as u16;
                let tr = sr * a16 + (canvas[dst_i] as u16) * inv;
                let tg = sg * a16 + (canvas[dst_i + 1] as u16) * inv;
                let tb = sb * a16 + (canvas[dst_i + 2] as u16) * inv;
                canvas[dst_i] = ((tr + (tr >> 8) + 1) >> 8) as u8;
                canvas[dst_i + 1] = ((tg + (tg >> 8) + 1) >> 8) as u8;
                canvas[dst_i + 2] = ((tb + (tb >> 8) + 1) >> 8) as u8;
            }
            dst_i += 3;
            src_i += 4;
        }
    }
}

pub fn render_lots(
    lots_dir: &Path,
    sprites_path: &Path,
    out_raw: &Path,
    ox: i32,
    oy: i32,
    x: i32,
    y: i32,
    w: i32,
    h: i32,
    tw: i32,
    max_level: Option<i32>,
    skip_blends: bool,
) -> Result<bool, String> {
    let (sprites, by_name) = read_sprites(sprites_path)?;
    let coords = cell_coords(ox, oy, x, y, w, h);
    let total_cells = coords.len().max(1);
    let wx0 = ox + x;
    let wy0 = oy + y;

    let n_threads = thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4)
        .min(8)
        .min(total_cells)
        .max(1);
    let next_cell = AtomicUsize::new(0);
    let done_cells = AtomicUsize::new(0);

    let mut per_thread: Vec<Result<BTreeMap<i32, (Vec<Square>, Vec<u32>)>, String>> =
        (0..n_threads).map(|_| Ok(BTreeMap::new())).collect();

    thread::scope(|scope| {
        for slot in &mut per_thread {
            let next_ref = &next_cell;
            let done_ref = &done_cells;
            let coords_ref = &coords;
            let by_name_ref = &by_name;
            scope.spawn(move || {
                let mut local_map: BTreeMap<i32, (Vec<Square>, Vec<u32>)> = BTreeMap::new();
                loop {
                    let i = next_ref.fetch_add(1, Ordering::Relaxed);
                    if i >= coords_ref.len() {
                        break;
                    }
                    let (cxw, cyw) = coords_ref[i];
                    if let Err(e) = collect_cell(
                        lots_dir,
                        cxw,
                        cyw,
                        wx0,
                        wy0,
                        w,
                        h,
                        max_level,
                        skip_blends,
                        by_name_ref,
                        &mut local_map,
                    ) {
                        *slot = Err(e);
                        return;
                    }
                    let d = done_ref.fetch_add(1, Ordering::Relaxed) + 1;
                    if d == total_cells || d % 8 == 0 {
                        let pct = (45 * d) / total_cells;
                        eprintln!("PROGRESS {pct} Reading compiled cells ({d}/{total_cells})…");
                    }
                }
                *slot = Ok(local_map);
            });
        }
    });

    let mut by_z: BTreeMap<i32, Vec<(Vec<Square>, Vec<u32>)>> = BTreeMap::new();
    let mut top = 0i32;
    let mut total_squares = 0usize;
    for res in per_thread {
        let map = res?;
        for (z, pair) in map {
            if pair.0.is_empty() {
                continue;
            }
            if z > top {
                top = z;
            }
            total_squares += pair.0.len();
            by_z.entry(z).or_default().push(pair);
        }
    }
    if by_z.is_empty() {
        return Ok(false);
    }
    if let Some(ml) = max_level {
        top = top.min(ml);
    }

    let half = tw / 2;
    let quarter = tw / 4;
    let level_px = ((LEVEL_PX * (tw as f64)) / 64.0).round() as i32;
    let width = (w + h) * half + tw;
    let height = (w + h) * quarter + 2 * tw + (top + 1) * level_px;
    let lift = (top + 1) * level_px;

    let npx = (width as usize) * (height as usize);
    let mut canvas = vec![0u8; npx * 3];
    for chunk in canvas.chunks_exact_mut(3) {
        chunk[0] = 24;
        chunk[1] = 26;
        chunk[2] = 28;
    }

    let total_squares = total_squares.max(1);
    let mut done_squares = 0usize;
    for (z, chunks) in by_z {
        if z > top {
            continue;
        }
        let level_count: usize = chunks.iter().map(|(s, _)| s.len()).sum();
        let pct = 45 + (50 * done_squares) / total_squares;
        eprintln!("PROGRESS {pct} Sorting level {z} ({level_count} tiles)…");

        // Flatten per-thread chunks for this level so each square sorts in one array.
        let mut flat: Vec<(Square, u32)> = Vec::with_capacity(level_count);
        let mut pools: Vec<Vec<u32>> = Vec::with_capacity(chunks.len());
        for (p_idx, (sqs, pool)) in chunks.into_iter().enumerate() {
            pools.push(pool);
            let p_u32 = p_idx as u32;
            for sq in sqs {
                flat.push((sq, p_u32));
            }
        }
        flat.sort_unstable_by_key(|(s, _)| (s.diag, s.dx, s.dy));

        let y_base = lift - z * level_px - (tw * 3) / 2;
        for (sq, p_idx) in flat {
            done_squares += 1;
            if (done_squares & 0xFFFF) == 0 {
                let pct = 45 + (50 * done_squares) / total_squares;
                eprintln!("PROGRESS {pct} Drawing level {z} ({done_squares}/{total_squares} tiles)…");
            }
            let px = (sq.dx - sq.dy) * half + h * half;
            let py = (sq.dx + sq.dy) * quarter + y_base;
            let pool = &pools[p_idx as usize];
            let s0 = sq.start as usize;
            let s1 = s0 + sq.len as usize;
            for &sp_idx in &pool[s0..s1] {
                blit_sprite(&mut canvas, width, height, px, py, &sprites[sp_idx as usize]);
            }
        }
    }

    let f = File::create(out_raw).map_err(|e| format!("{}: {e}", out_raw.display()))?;
    let mut bw = BufWriter::new(f);
    bw.write_all(b"RAW1").map_err(|e| format!("write raw header: {e}"))?;
    bw.write_all(&(width as u32).to_le_bytes()).map_err(|e| format!("write width: {e}"))?;
    bw.write_all(&(height as u32).to_le_bytes()).map_err(|e| format!("write height: {e}"))?;
    bw.write_all(&0u32.to_le_bytes()).map_err(|e| format!("write pad: {e}"))?;
    bw.write_all(&canvas).map_err(|e| format!("write canvas: {e}"))?;
    bw.flush().map_err(|e| format!("flush canvas: {e}"))?;
    Ok(true)
}
