//! Native footprint placement engine (`--footprints`).
//!
//! Holds the map's `avoid`, `occupied`, and `lots` grids in memory across a
//! persistent stdin/stdout session and runs the exact same nudge, road-cut,
//! connected-component hug, clear-box lot trim, and tile claiming logic as
//! `knoxbuild/footprint.py`.

use std::io::{self, BufReader, BufWriter, Read, Write};

use super::die;

const MIN_TILES: usize = 16;
const NUDGE_TILES: i32 = 5;
const WIDE_NUDGE_TILES: i32 = 12;
const ROAD_SHARE_MAX: f64 = 0.10;
const ROAD_WEIGHT: u8 = 2;

const FLAG_HAS_AVOID: u8 = 1 << 0;
const FLAG_HAS_LOTS: u8 = 1 << 1;
const FLAG_HAS_INIT_OCC: u8 = 1 << 2;
const FLAG_HAS_INIT_LOTS: u8 = 1 << 3;

const CMD_QUIT: u8 = 0;
const CMD_PLACE: u8 = 1;

const STATUS_OK: u8 = 0;
const STATUS_ROAD: u8 = 1;
const STATUS_OUTSIDE: u8 = 2;
const STATUS_TAKEN: u8 = 3;

#[derive(Debug, PartialEq, Eq)]
pub enum PlaceStatus {
    Ok {
        fx0: i32,
        fy0: i32,
        fw: usize,
        fh: usize,
        ox: i32,
        oy: i32,
        full_rect: bool,
        mask: Vec<u8>,
    },
    Road,
    Outside,
    Taken,
}

pub struct FootprintState {
    map_w: usize,
    map_h: usize,
    avoid: Option<Vec<u8>>,
    occupied: Vec<u8>,
    lots: Option<Vec<u8>>,
}

impl FootprintState {
    pub fn new(
        map_w: usize,
        map_h: usize,
        avoid: Option<Vec<u8>>,
        occupied: Vec<u8>,
        lots: Option<Vec<u8>>,
    ) -> Self {
        Self {
            map_w,
            map_h,
            avoid,
            occupied,
            lots,
        }
    }

    #[inline]
    fn in_bounds(&self, x0: i32, y0: i32, w: i32, h: i32) -> bool {
        let map_w = self.map_w as i32;
        let map_h = self.map_h as i32;
        map_w.min(x0 + w) > 0.max(x0) && map_h.min(y0 + h) > 0.max(y0)
    }

    fn road_share(
        &self,
        mask: &[u8],
        w: usize,
        h: usize,
        mask_sum: usize,
        x0: i32,
        y0: i32,
        full_rect: bool,
    ) -> f64 {
        if mask_sum == 0 {
            return 0.0;
        }
        let avoid = match self.avoid.as_deref() {
            Some(a) => a,
            None => return 0.0,
        };
        let map_w = self.map_w as i32;
        let map_h = self.map_h as i32;
        let cx0 = 0.max(x0);
        let cy0 = 0.max(y0);
        let cx1 = map_w.min(x0 + w as i32);
        let cy1 = map_h.min(y0 + h as i32);
        if cx1 <= cx0 || cy1 <= cy0 {
            return 0.0;
        }
        let mut road_cnt: usize = 0;
        let mw = self.map_w;
        if full_rect {
            for y in cy0..cy1 {
                let row = &avoid[(y as usize) * mw..];
                for x in cx0..cx1 {
                    if row[x as usize] >= ROAD_WEIGHT {
                        road_cnt += 1;
                    }
                }
            }
        } else {
            for y in cy0..cy1 {
                let my = (y - y0) as usize;
                let mrow = &mask[my * w..];
                let arow = &avoid[(y as usize) * mw..];
                for x in cx0..cx1 {
                    let mx = (x - x0) as usize;
                    if mrow[mx] != 0 && arow[x as usize] >= ROAD_WEIGHT {
                        road_cnt += 1;
                    }
                }
            }
        }
        (road_cnt as f64) / (mask_sum as f64)
    }

    fn occ_count(
        &self,
        mask: &[u8],
        w: usize,
        h: usize,
        x0: i32,
        y0: i32,
        full_rect: bool,
    ) -> i32 {
        let map_w = self.map_w as i32;
        let map_h = self.map_h as i32;
        let cx0 = 0.max(x0);
        let cy0 = 0.max(y0);
        let cx1 = map_w.min(x0 + w as i32);
        let cy1 = map_h.min(y0 + h as i32);
        if cx1 <= cx0 || cy1 <= cy0 {
            return 0;
        }
        let mut cnt: i32 = 0;
        let mw = self.map_w;
        if full_rect {
            for y in cy0..cy1 {
                let row = &self.occupied[(y as usize) * mw..];
                for x in cx0..cx1 {
                    cnt += (row[x as usize] != 0) as i32;
                }
            }
        } else {
            for y in cy0..cy1 {
                let my = (y - y0) as usize;
                let mrow = &mask[my * w..];
                let orow = &self.occupied[(y as usize) * mw..];
                for x in cx0..cx1 {
                    let mx = (x - x0) as usize;
                    if mrow[mx] != 0 && orow[x as usize] != 0 {
                        cnt += 1;
                    }
                }
            }
        }
        cnt
    }

    fn window_sums(
        &self,
        grid: &[u8],
        is_bool: bool,
        mask: &[u8],
        w: usize,
        h: usize,
        x0: i32,
        y0: i32,
        radius: i32,
        full_rect: bool,
    ) -> Vec<i32> {
        let r = radius as usize;
        let side = 2 * r + 1;
        let win_h = h + 2 * r;
        let win_w = w + 2 * r;
        let gx0 = x0 - radius;
        let gy0 = y0 - radius;
        let gx1 = gx0 + win_w as i32;
        let gy1 = gy0 + win_h as i32;
        let cx0 = 0.max(gx0);
        let cy0 = 0.max(gy0);
        let cx1 = (self.map_w as i32).min(gx1);
        let cy1 = (self.map_h as i32).min(gy1);
        let mw = self.map_w;

        if full_rect {
            let pw = win_w + 1;
            let ph = win_h + 1;
            let mut ps = vec![0i32; ph * pw];
            if cx1 > cx0 && cy1 > cy0 {
                for y in cy0..cy1 {
                    let wy = 1 + (y - gy0) as usize;
                    let grow = &grid[(y as usize) * mw..];
                    let prow = &mut ps[wy * pw..];
                    for x in cx0..cx1 {
                        let wx = 1 + (x - gx0) as usize;
                        let v = grow[x as usize];
                        prow[wx] = if is_bool { (v != 0) as i32 } else { v as i32 };
                    }
                }
            }
            for y in 1..ph {
                let mut row_sum = 0i32;
                for x in 1..pw {
                    row_sum += ps[y * pw + x];
                    ps[y * pw + x] = ps[(y - 1) * pw + x] + row_sum;
                }
            }
            let mut out = vec![0i32; side * side];
            for iy in 0..side {
                for ix in 0..side {
                    out[iy * side + ix] = ps[(iy + h) * pw + (ix + w)]
                        - ps[iy * pw + (ix + w)]
                        - ps[(iy + h) * pw + ix]
                        + ps[iy * pw + ix];
                }
            }
            return out;
        }

        let mut win = vec![0i32; win_h * win_w];
        if cx1 > cx0 && cy1 > cy0 {
            for y in cy0..cy1 {
                let wy = (y - gy0) as usize;
                let grow = &grid[(y as usize) * mw..];
                let wrow = &mut win[wy * win_w..];
                for x in cx0..cx1 {
                    let wx = (x - gx0) as usize;
                    let v = grow[x as usize];
                    wrow[wx] = if is_bool { (v != 0) as i32 } else { v as i32 };
                }
            }
        }
        // Collect active mask pixels once for tight inner loop.
        let mut active: Vec<(usize, usize)> = Vec::new();
        for my in 0..h {
            let mrow = &mask[my * w..];
            for mx in 0..w {
                if mrow[mx] != 0 {
                    active.push((my, mx));
                }
            }
        }
        let mut out = vec![0i32; side * side];
        for iy in 0..side {
            for ix in 0..side {
                let mut sum = 0i32;
                for &(my, mx) in &active {
                    sum += win[(iy + my) * win_w + (ix + mx)];
                }
                out[iy * side + ix] = sum;
            }
        }
        out
    }

    fn clear_of(
        &self,
        mask: &[u8],
        w: usize,
        h: usize,
        mask_sum: usize,
        x0: i32,
        y0: i32,
        full_rect: bool,
    ) -> (i32, i32) {
        let avoid = match self.avoid.as_deref() {
            Some(a) => a,
            None => return (x0, y0),
        };
        if !self.in_bounds(x0, y0, w as i32, h as i32) {
            return (x0, y0);
        }
        let map_w = self.map_w as i32;
        let map_h = self.map_h as i32;
        let cx0 = 0.max(x0);
        let cy0 = 0.max(y0);
        let cx1 = map_w.min(x0 + w as i32);
        let cy1 = map_h.min(y0 + h as i32);
        let mw = self.map_w;

        let mut here_avoid: i32 = 0;
        let mut here_occ: i32 = 0;
        if full_rect {
            for y in cy0..cy1 {
                let arow = &avoid[(y as usize) * mw..];
                let orow = &self.occupied[(y as usize) * mw..];
                for x in cx0..cx1 {
                    here_avoid += arow[x as usize] as i32;
                    here_occ += (orow[x as usize] != 0) as i32;
                }
            }
        } else {
            for y in cy0..cy1 {
                let my = (y - y0) as usize;
                let mrow = &mask[my * w..];
                let arow = &avoid[(y as usize) * mw..];
                let orow = &self.occupied[(y as usize) * mw..];
                for x in cx0..cx1 {
                    let mx = (x - x0) as usize;
                    if mrow[mx] != 0 {
                        here_avoid += arow[x as usize] as i32;
                        here_occ += (orow[x as usize] != 0) as i32;
                    }
                }
            }
        }
        if here_avoid == 0 {
            return (x0, y0);
        }

        let side = (2 * NUDGE_TILES + 1) as usize;
        let avoid_sums = self.window_sums(avoid, false, mask, w, h, x0, y0, NUDGE_TILES, full_rect);
        let occ_sums = self.window_sums(
            &self.occupied,
            true,
            mask,
            w,
            h,
            x0,
            y0,
            NUDGE_TILES,
            full_rect,
        );

        let mut clear: Option<(i32, i32)> = None;
        let mut clear_score = f64::INFINITY;
        let mut best = (0i32, 0i32);
        let mut best_score = (here_avoid * 4 + here_occ) as f64;

        for ox in -NUDGE_TILES..=NUDGE_TILES {
            let ix = (ox + NUDGE_TILES) as usize;
            for oy in -NUDGE_TILES..=NUDGE_TILES {
                if !self.in_bounds(x0 + ox, y0 + oy, w as i32, h as i32) {
                    continue;
                }
                let iy = (oy + NUDGE_TILES) as usize;
                let ca = avoid_sums[iy * side + ix];
                let co = occ_sums[iy * side + ix];
                let moved = (ox.abs() + oy.abs()) as f64 * 0.5;
                if ca == 0 && (co as f64) + moved < clear_score {
                    clear = Some((ox, oy));
                    clear_score = (co as f64) + moved;
                }
                let score = (ca * 4 + co) as f64 + moved;
                if score < best_score {
                    best = (ox, oy);
                    best_score = score;
                }
            }
        }

        let (mut ox, mut oy) = clear.unwrap_or(best);
        if self.road_share(mask, w, h, mask_sum, x0 + ox, y0 + oy, full_rect) > ROAD_SHARE_MAX {
            let mut found: Option<(i32, i32, i32)> = None;
            for r in (NUDGE_TILES + 1)..=WIDE_NUDGE_TILES {
                for ox2 in -r..=r {
                    for oy2 in -r..=r {
                        if ox2.abs().max(oy2.abs()) != r
                            || !self.in_bounds(x0 + ox2, y0 + oy2, w as i32, h as i32)
                        {
                            continue;
                        }
                        let ax0 = x0 + ox2;
                        let ay0 = y0 + oy2;
                        if self.road_share(mask, w, h, mask_sum, ax0, ay0, full_rect)
                            <= ROAD_SHARE_MAX
                        {
                            let co = self.occ_count(mask, w, h, ax0, ay0, full_rect);
                            if found.is_none() || co < found.unwrap().0 {
                                found = Some((co, ox2, oy2));
                            }
                        }
                    }
                }
                if let Some((_, fx, fy)) = found {
                    ox = fx;
                    oy = fy;
                    break;
                }
            }
        }
        (x0 + ox, y0 + oy)
    }

    pub fn place_mask(
        &mut self,
        x0_in: i32,
        y0_in: i32,
        w: usize,
        h: usize,
        min_side: f64,
        full_rect_in: bool,
        mask_in: &[u8],
    ) -> PlaceStatus {
        let mask_sum_in: usize = if full_rect_in {
            w * h
        } else {
            mask_in.iter().filter(|&&v| v != 0).count()
        };

        let (x0, y0) = if self.avoid.is_some() {
            self.clear_of(mask_in, w, h, mask_sum_in, x0_in, y0_in, full_rect_in)
        } else {
            (x0_in, y0_in)
        };
        let ox = x0 - x0_in;
        let oy = y0 - y0_in;

        if self.avoid.is_some()
            && self.road_share(mask_in, w, h, mask_sum_in, x0, y0, full_rect_in) > ROAD_SHARE_MAX
        {
            return PlaceStatus::Road;
        }

        // Clip to map bounds.
        let map_w = self.map_w as i32;
        let map_h = self.map_h as i32;
        let cx0 = 0.max(x0);
        let cy0 = 0.max(y0);
        let cx1 = map_w.min(x0 + w as i32);
        let cy1 = map_h.min(y0 + h as i32);
        if cx1 <= cx0 || cy1 <= cy0 {
            return PlaceStatus::Outside;
        }

        let cw = (cx1 - cx0) as usize;
        let ch = (cy1 - cy0) as usize;
        let mw = self.map_w;
        let mut mask = vec![0u8; ch * cw];
        let mut count: usize = 0;

        for y in 0..ch {
            let gy = (cy0 as usize) + y;
            let my = (cy0 - y0) as usize + y;
            let orow = &self.occupied[gy * mw..];
            let arow = self.avoid.as_deref().map(|a| &a[gy * mw..]);
            let dst = &mut mask[y * cw..];
            for x in 0..cw {
                let gx = (cx0 as usize) + x;
                let mx = (cx0 - x0) as usize + x;
                let alive = if full_rect_in {
                    true
                } else {
                    mask_in[my * w + mx] != 0
                };
                if !alive {
                    continue;
                }
                if let Some(ar) = arow {
                    if ar[gx] >= ROAD_WEIGHT {
                        continue;
                    }
                }
                if orow[gx] != 0 {
                    continue;
                }
                dst[x] = 1;
                count += 1;
            }
        }

        if count < MIN_TILES {
            return PlaceStatus::Taken;
        }

        let (mut mask, mut fw, mut fh, mut fx0, mut fy0, mut count) =
            hug(&mask, cw, ch, cx0, cy0, count);
        if count < MIN_TILES {
            return PlaceStatus::Taken;
        }

        if let Some(ref lots) = self.lots {
            let mut any_blocked = false;
            let mut blocked = vec![0u8; fh * fw];
            for y in 0..fh {
                let gy = (fy0 as usize) + y;
                let lrow = &lots[gy * mw..];
                let brow = &mut blocked[y * fw..];
                for x in 0..fw {
                    let v = lrow[(fx0 as usize) + x];
                    if v != 0 {
                        brow[x] = 1;
                        any_blocked = true;
                    }
                }
            }
            if any_blocked {
                let (by0, by1, bx0, bx1) = clear_box(&mask, &blocked, fw, fh);
                let bw = bx1 - bx0;
                let bh = by1 - by0;
                let mut sub = vec![0u8; bh * bw];
                let mut sub_count: usize = 0;
                for y in 0..bh {
                    let srow = &mask[(by0 + y) * fw..];
                    let drow = &mut sub[y * bw..];
                    for x in 0..bw {
                        let v = srow[bx0 + x];
                        if v != 0 {
                            drow[x] = 1;
                            sub_count += 1;
                        }
                    }
                }
                let (m2, w2, h2, x2, y2, c2) =
                    hug(&sub, bw, bh, fx0 + bx0 as i32, fy0 + by0 as i32, sub_count);
                mask = m2;
                fw = w2;
                fh = h2;
                fx0 = x2;
                fy0 = y2;
                count = c2;
                if count < MIN_TILES || (fh.min(fw) as f64) < (3.0_f64).max(min_side) {
                    return PlaceStatus::Taken;
                }
            }
        }

        // Claim tiles in `occupied` and rectangle in `lots`.
        for y in 0..fh {
            let gy = (fy0 as usize) + y;
            let orow = &mut self.occupied[gy * mw..];
            let mrow = &mask[y * fw..];
            for x in 0..fw {
                if mrow[x] != 0 {
                    orow[(fx0 as usize) + x] = 1;
                }
            }
        }
        if let Some(ref mut lots) = self.lots {
            for y in 0..fh {
                let gy = (fy0 as usize) + y;
                let lrow = &mut lots[gy * mw..];
                for x in 0..fw {
                    lrow[(fx0 as usize) + x] = 1;
                }
            }
        }

        let full_out = count == fw * fh;
        PlaceStatus::Ok {
            fx0,
            fy0,
            fw,
            fh,
            ox,
            oy,
            full_rect: full_out,
            mask: if full_out { Vec::new() } else { mask },
        }
    }
}

/// Keep only the biggest 4-connected component of `mask`, trimmed to its tight bounding box.
fn hug(
    mask: &[u8],
    w: usize,
    h: usize,
    x0: i32,
    y0: i32,
    count: usize,
) -> (Vec<u8>, usize, usize, i32, i32, usize) {
    if w == 0 || h == 0 || count == 0 {
        return (Vec::new(), 0, 0, x0, y0, 0);
    }
    if count == w * h {
        return (mask.to_vec(), w, h, x0, y0, count);
    }

    let mut seen = vec![0u8; h * w];
    let mut best: Vec<(usize, usize)> = Vec::new();
    let mut stack: Vec<(usize, usize)> = Vec::new();
    let mut piece: Vec<(usize, usize)> = Vec::new();

    for y in 0..h {
        for x in 0..w {
            let idx = y * w + x;
            if mask[idx] == 0 || seen[idx] != 0 {
                continue;
            }
            piece.clear();
            stack.clear();
            stack.push((y, x));
            seen[idx] = 1;
            while let Some((cy, cx)) = stack.pop() {
                piece.push((cy, cx));
                if cy + 1 < h {
                    let ni = (cy + 1) * w + cx;
                    if mask[ni] != 0 && seen[ni] == 0 {
                        seen[ni] = 1;
                        stack.push((cy + 1, cx));
                    }
                }
                if cy > 0 {
                    let ni = (cy - 1) * w + cx;
                    if mask[ni] != 0 && seen[ni] == 0 {
                        seen[ni] = 1;
                        stack.push((cy - 1, cx));
                    }
                }
                if cx + 1 < w {
                    let ni = cy * w + (cx + 1);
                    if mask[ni] != 0 && seen[ni] == 0 {
                        seen[ni] = 1;
                        stack.push((cy, cx + 1));
                    }
                }
                if cx > 0 {
                    let ni = cy * w + (cx - 1);
                    if mask[ni] != 0 && seen[ni] == 0 {
                        seen[ni] = 1;
                        stack.push((cy, cx - 1));
                    }
                }
            }
            if piece.len() > best.len() {
                std::mem::swap(&mut best, &mut piece);
            }
        }
    }

    if best.is_empty() {
        return (Vec::new(), 0, 0, x0, y0, 0);
    }

    let mut min_y = h;
    let mut max_y = 0usize;
    let mut min_x = w;
    let mut max_x = 0usize;
    for &(y, x) in &best {
        if y < min_y {
            min_y = y;
        }
        if y > max_y {
            max_y = y;
        }
        if x < min_x {
            min_x = x;
        }
        if x > max_x {
            max_x = x;
        }
    }
    let nw = max_x - min_x + 1;
    let nh = max_y - min_y + 1;
    let mut out = vec![0u8; nh * nw];
    for &(y, x) in &best {
        out[(y - min_y) * nw + (x - min_x)] = 1;
    }
    let nc = best.len();
    (out, nw, nh, x0 + min_x as i32, y0 + min_y as i32, nc)
}

/// Largest-mask axis-aligned box containing no `blocked` tile, half-open `(by0, by1, bx0, bx1)`.
fn clear_box(mask: &[u8], blocked: &[u8], w: usize, h: usize) -> (usize, usize, usize, usize) {
    let mut cb: Vec<usize> = Vec::with_capacity(w + 1);
    cb.push(0);
    for x in 1..w {
        let mut diff = false;
        for y in 0..h {
            if blocked[y * w + x] != blocked[y * w + (x - 1)] {
                diff = true;
                break;
            }
        }
        if diff {
            cb.push(x);
        }
    }
    cb.push(w);

    let mut rb: Vec<usize> = Vec::with_capacity(h + 1);
    rb.push(0);
    for y in 1..h {
        let row_a = &blocked[y * w..(y + 1) * w];
        let row_b = &blocked[(y - 1) * w..y * w];
        if row_a != row_b {
            rb.push(y);
        }
    }
    rb.push(h);

    let sh = rb.len() - 1;
    let sw = cb.len() - 1;

    // 2D prefix sum of `mask` on full (h+1) x (w+1) grid.
    let pw = w + 1;
    let mut held = vec![0i32; (h + 1) * pw];
    for y in 0..h {
        let mut row_sum = 0i32;
        for x in 0..w {
            row_sum += (mask[y * w + x] != 0) as i32;
            held[(y + 1) * pw + (x + 1)] = held[y * pw + (x + 1)] + row_sum;
        }
    }

    let mut best = (0i32, 0usize, 0usize, 0usize, 0usize);
    let mut heights = vec![0usize; sw];
    let mut stack: Vec<(usize, usize)> = Vec::with_capacity(sw + 1);

    for y in 0..sh {
        let ry = rb[y];
        for x in 0..sw {
            if blocked[ry * w + cb[x]] != 0 {
                heights[x] = 0;
            } else {
                heights[x] += 1;
            }
        }
        stack.clear();
        for x in 0..=sw {
            let tall = if x < sw { heights[x] } else { 0 };
            let mut start = x;
            while let Some(&(s, high)) = stack.last() {
                if high >= tall {
                    stack.pop();
                    start = s;
                    let top = y + 1 - high;
                    let r_bot = rb[y + 1];
                    let r_top = rb[top];
                    let c_r = cb[x];
                    let c_l = cb[start];
                    let tiles = held[r_bot * pw + c_r]
                        - held[r_top * pw + c_r]
                        - held[r_bot * pw + c_l]
                        + held[r_top * pw + c_l];
                    if tiles > best.0 {
                        best = (tiles, r_top, r_bot, c_l, c_r);
                    }
                } else {
                    break;
                }
            }
            stack.push((start, tall));
        }
    }
    (best.1, best.2, best.3, best.4)
}

fn read_exact_or_eof<R: Read>(r: &mut R, buf: &mut [u8]) -> bool {
    match r.read_exact(buf) {
        Ok(()) => true,
        Err(e) if e.kind() == io::ErrorKind::UnexpectedEof => false,
        Err(e) => die(&format!("footprints read error: {e}")),
    }
}

fn read_u8<R: Read>(r: &mut R) -> u8 {
    let mut b = [0u8; 1];
    if let Err(e) = r.read_exact(&mut b) {
        die(&format!("footprints short read (u8): {e}"));
    }
    b[0]
}

fn read_i32<R: Read>(r: &mut R) -> i32 {
    let mut b = [0u8; 4];
    if let Err(e) = r.read_exact(&mut b) {
        die(&format!("footprints short read (i32): {e}"));
    }
    i32::from_le_bytes(b)
}

fn read_f64<R: Read>(r: &mut R) -> f64 {
    let mut b = [0u8; 8];
    if let Err(e) = r.read_exact(&mut b) {
        die(&format!("footprints short read (f64): {e}"));
    }
    f64::from_le_bytes(b)
}

fn read_vec<R: Read>(r: &mut R, n: usize) -> Vec<u8> {
    let mut buf = vec![0u8; n];
    if let Err(e) = r.read_exact(&mut buf) {
        die(&format!("footprints short read ({n} bytes): {e}"));
    }
    buf
}

pub fn run() {
    let stdin = io::stdin();
    let mut r = BufReader::new(stdin.lock());
    let mut magic = [0u8; 4];
    if let Err(e) = r.read_exact(&mut magic) {
        die(&format!("footprints header read failed: {e}"));
    }
    if &magic != b"KFP1" {
        die("not a version 1 footprints stream");
    }
    let map_w = read_i32(&mut r);
    let map_h = read_i32(&mut r);
    let flags = read_u8(&mut r);
    if map_w <= 0 || map_h <= 0 {
        die("invalid footprints map dimensions");
    }
    let (mw, mh) = (map_w as usize, map_h as usize);
    let Some(n) = mw.checked_mul(mh).filter(|&n| n <= 400_000_000) else {
        die("footprints map too large");
    };

    let avoid = if (flags & FLAG_HAS_AVOID) != 0 {
        Some(read_vec(&mut r, n))
    } else {
        None
    };
    let occupied = if (flags & FLAG_HAS_INIT_OCC) != 0 {
        read_vec(&mut r, n)
    } else {
        vec![0u8; n]
    };
    let lots = if (flags & FLAG_HAS_LOTS) != 0 {
        if (flags & FLAG_HAS_INIT_LOTS) != 0 {
            Some(read_vec(&mut r, n))
        } else {
            Some(vec![0u8; n])
        }
    } else {
        None
    };

    let mut state = FootprintState::new(mw, mh, avoid, occupied, lots);
    let stdout = io::stdout();
    let mut out = BufWriter::new(stdout.lock());
    if out.write_all(b"KFP1").and_then(|_| out.flush()).is_err() {
        return;
    }

    let mut mask_buf: Vec<u8> = Vec::new();
    let mut cmd_byte = [0u8; 1];
    while read_exact_or_eof(&mut r, &mut cmd_byte) {
        match cmd_byte[0] {
            CMD_QUIT => break,
            CMD_PLACE => {
                let x0 = read_i32(&mut r);
                let y0 = read_i32(&mut r);
                let w = read_i32(&mut r);
                let h = read_i32(&mut r);
                let min_side = read_f64(&mut r);
                let is_full = read_u8(&mut r) != 0;
                if w < 0 || h < 0 {
                    die("negative footprint mask dimensions");
                }
                let (wu, hu) = (w as usize, h as usize);
                let Some(mn) = wu.checked_mul(hu).filter(|&mn| mn <= 100_000_000) else {
                    die("footprint mask too large");
                };
                if is_full {
                    mask_buf.clear();
                } else {
                    mask_buf.resize(mn, 0);
                    if let Err(e) = r.read_exact(&mut mask_buf) {
                        die(&format!("footprints mask read error: {e}"));
                    }
                }
                let res = state.place_mask(x0, y0, wu, hu, min_side, is_full, &mask_buf);
                let write_res = match res {
                    PlaceStatus::Ok {
                        fx0,
                        fy0,
                        fw,
                        fh,
                        ox,
                        oy,
                        full_rect,
                        mask,
                    } => {
                        let mut hdr = [0u8; 26];
                        hdr[0] = STATUS_OK;
                        hdr[1..5].copy_from_slice(&fx0.to_le_bytes());
                        hdr[5..9].copy_from_slice(&fy0.to_le_bytes());
                        hdr[9..13].copy_from_slice(&(fw as i32).to_le_bytes());
                        hdr[13..17].copy_from_slice(&(fh as i32).to_le_bytes());
                        hdr[17..21].copy_from_slice(&ox.to_le_bytes());
                        hdr[21..25].copy_from_slice(&oy.to_le_bytes());
                        hdr[25] = u8::from(full_rect);
                        out.write_all(&hdr).and_then(|_| {
                            if full_rect {
                                Ok(())
                            } else {
                                out.write_all(&mask)
                            }
                        })
                    }
                    PlaceStatus::Road => out.write_all(&[STATUS_ROAD]),
                    PlaceStatus::Outside => out.write_all(&[STATUS_OUTSIDE]),
                    PlaceStatus::Taken => out.write_all(&[STATUS_TAKEN]),
                };
                if write_res.and_then(|_| out.flush()).is_err() {
                    break;
                }
            }
            other => die(&format!("unknown footprints command: {other}")),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn place_clean_rect_and_reject_overlap() {
        let mut st = FootprintState::new(40, 40, None, vec![0u8; 40 * 40], Some(vec![0u8; 40 * 40]));
        let r1 = st.place_mask(10, 10, 8, 6, 3.0, true, &[]);
        assert_eq!(
            r1,
            PlaceStatus::Ok {
                fx0: 10,
                fy0: 10,
                fw: 8,
                fh: 6,
                ox: 0,
                oy: 0,
                full_rect: true,
                mask: Vec::new(),
            }
        );
        // Exact same spot is now completely taken.
        let r2 = st.place_mask(10, 10, 8, 6, 3.0, true, &[]);
        assert_eq!(r2, PlaceStatus::Taken);
    }

    #[test]
    fn nudge_off_road() {
        let (w, h) = (60, 60);
        let mut avoid = vec![0u8; w * h];
        // Horizontal road at y = 20..24 (weight 2).
        for y in 20..24 {
            for x in 0..w {
                avoid[y * w + x] = 2;
            }
        }
        let mut st = FootprintState::new(w, h, Some(avoid), vec![0u8; w * h], None);
        // Building 8x6 sitting at y = 18..24 overlaps road by 4 rows -> should nudge up to y = 14 (oy = -4).
        let res = st.place_mask(20, 18, 8, 6, 3.0, true, &[]);
        match res {
            PlaceStatus::Ok { fx0, fy0, fw, fh, ox, oy, .. } => {
                assert_eq!((fx0, fy0, fw, fh, ox, oy), (20, 14, 8, 6, 0, -4));
            }
            other => panic!("expected Ok, got {other:?}"),
        }
    }

    #[test]
    fn hug_keeps_largest_component() {
        // 8x6 mask with two disconnected blobs: 2x2 (4 tiles) and 4x5 (20 tiles).
        let mut mask = vec![0u8; 8 * 6];
        for y in 0..2 {
            for x in 0..2 {
                mask[y * 8 + x] = 1;
            }
        }
        for y in 1..6 {
            for x in 4..8 {
                mask[y * 8 + x] = 1;
            }
        }
        let (out, nw, nh, fx0, fy0, cnt) = hug(&mask, 8, 6, 10, 20, 24);
        assert_eq!((nw, nh, fx0, fy0, cnt), (4, 5, 14, 21, 20));
        assert!(out.iter().all(|&v| v == 1));
    }

    #[test]
    fn clear_box_trims_lot_overlap() {
        // 10x10 full mask, blocked in top-left 4x4.
        // Best clear box is either x in 4..10 (6x10 = 60) or y in 4..10 (10x6 = 60).
        let mask = vec![1u8; 10 * 10];
        let mut blocked = vec![0u8; 10 * 10];
        for y in 0..4 {
            for x in 0..4 {
                blocked[y * 10 + x] = 1;
            }
        }
        let (by0, by1, bx0, bx1) = clear_box(&mask, &blocked, 10, 10);
        assert_eq!((by1 - by0) * (bx1 - bx0), 60);
    }
}
