//! Smooth one-tile notches and bumps along road and pavement edges.
use super::{die, Reader};
use std::io::{self, Write};

#[inline]
fn pack_rgb(rgb: &[u8]) -> u32 {
    ((rgb[0] as u32) << 16) | ((rgb[1] as u32) << 8) | (rgb[2] as u32)
}

#[inline]
fn write_rgb(ground: &mut [u8], idx: usize, rgb: [u8; 3]) {
    let off = idx * 3;
    ground[off] = rgb[0];
    ground[off + 1] = rgb[1];
    ground[off + 2] = rgb[2];
}

#[inline]
fn read_rgb(ground: &[u8], idx: usize) -> [u8; 3] {
    let off = idx * 3;
    [ground[off], ground[off + 1], ground[off + 2]]
}

fn read_palette(r: &mut Reader<impl io::Read>, label: &str) -> Vec<u32> {
    let count = r.i32();
    if !(0..=4096).contains(&count) {
        die(&format!("invalid {label} palette size"));
    }
    let raw = r.take(3 * count as usize);
    raw.chunks_exact(3).map(pack_rgb).collect()
}

fn mark_two_tile_bumps(
    fg: &[bool],
    bg: &[bool],
    back: &[bool],
    w: usize,
    h: usize,
    out: &mut [bool],
) {
    if h >= 3 && w >= 4 {
        for y in 1..(h - 1) {
            let row = y * w;
            for x in 1..(w - 2) {
                let i = row + x;
                let pair = fg[i] && fg[i + 1] && bg[i - 1] && bg[i + 2];
                if !pair {
                    continue;
                }
                let n = bg[i - w]
                    && bg[i - w + 1]
                    && back[i + w - 1]
                    && back[i + w]
                    && back[i + w + 1]
                    && back[i + w + 2];
                let s = bg[i + w]
                    && bg[i + w + 1]
                    && back[i - w - 1]
                    && back[i - w]
                    && back[i - w + 1]
                    && back[i - w + 2];
                if n || s {
                    out[i] = true;
                    out[i + 1] = true;
                }
            }
        }
    }
    if h >= 4 && w >= 3 {
        for y in 1..(h - 2) {
            let row = y * w;
            for x in 1..(w - 1) {
                let i = row + x;
                let pair = fg[i] && fg[i + w] && bg[i - w] && bg[i + 2 * w];
                if !pair {
                    continue;
                }
                let w_m = bg[i - 1]
                    && bg[i + w - 1]
                    && back[i - w + 1]
                    && back[i + 1]
                    && back[i + w + 1]
                    && back[i + 2 * w + 1];
                let e_m = bg[i + 1]
                    && bg[i + w + 1]
                    && back[i - w - 1]
                    && back[i - 1]
                    && back[i + w - 1]
                    && back[i + 2 * w - 1];
                if w_m || e_m {
                    out[i] = true;
                    out[i + w] = true;
                }
            }
        }
    }
}

fn mark_two_tile_notches(
    fg: &[bool],
    bg: &[bool],
    w: usize,
    h: usize,
    out: &mut [bool],
) {
    if h >= 3 && w >= 4 {
        for y in 1..(h - 1) {
            let row = y * w;
            for x in 1..(w - 2) {
                let i = row + x;
                let pair = fg[i] && fg[i + 1] && bg[i - 1] && bg[i + 2];
                if !pair {
                    continue;
                }
                let n = fg[i - w] && fg[i - w + 1] && bg[i + w] && bg[i + w + 1];
                let s = fg[i + w] && fg[i + w + 1] && bg[i - w] && bg[i - w + 1];
                if n || s {
                    out[i] = true;
                    out[i + 1] = true;
                }
            }
        }
    }
    if h >= 4 && w >= 3 {
        for y in 1..(h - 2) {
            let row = y * w;
            for x in 1..(w - 1) {
                let i = row + x;
                let pair = fg[i] && fg[i + w] && bg[i - w] && bg[i + 2 * w];
                if !pair {
                    continue;
                }
                let w_m = fg[i - 1] && fg[i + w - 1] && bg[i + 1] && bg[i + w + 1];
                let e_m = fg[i + 1] && fg[i + w + 1] && bg[i - 1] && bg[i + w - 1];
                if w_m || e_m {
                    out[i] = true;
                    out[i + w] = true;
                }
            }
        }
    }
}

pub fn smooth_strip(
    ground: &mut [u8],
    w: usize,
    h: usize,
    asphalt: &[u32],
    pave_rgb: [u8; 3],
    medium_grass_rgb: [u8; 3],
    verge_pal: &[u32],
) {
    let n = w * h;
    let pave_key = pack_rgb(&pave_rgb);
    let mut road = vec![false; n];
    let mut pave = vec![false; n];
    let mut verge = vec![false; n];
    let mut road_border = vec![false; n];
    let mut pave_or_road = vec![false; n];

    let mut notch = vec![false; n];
    let mut bump = vec![false; n];
    let mut lonep = vec![false; n];
    let mut mend = vec![false; n];
    let mut pave_bump = vec![false; n];
    let mut pave_notch = vec![false; n];

    for _ in 0..10 {
        for i in 0..n {
            let k = pack_rgb(&ground[i * 3..i * 3 + 3]);
            let is_r = asphalt.contains(&k);
            let is_p = k == pave_key;
            let is_v = verge_pal.contains(&k);
            road[i] = is_r;
            pave[i] = is_p;
            verge[i] = is_v;
            road_border[i] = is_p || is_v;
            pave_or_road[i] = is_p || is_r;
        }

        let mut any_change = false;
        for y in 0..h {
            let row = y * w;
            for x in 0..w {
                let i = row + x;
                let rb = road_border[i];
                let r = road[i];
                let p = pave[i];
                let v = verge[i];

                let n_v = (y > 0 && y + 1 < h && road[i - w] && road[i + w])
                    || (x > 0 && x + 1 < w && road[i - 1] && road[i + 1]);
                let is_notch = rb && n_v;
                notch[i] = is_notch;

                let mut border_count = 0u8;
                let mut ortho_pave = 0u8;
                let mut verge_count = 0u8;
                if x > 0 {
                    border_count += road_border[i - 1] as u8;
                    ortho_pave += pave[i - 1] as u8;
                    verge_count += verge[i - 1] as u8;
                }
                if x + 1 < w {
                    border_count += road_border[i + 1] as u8;
                    ortho_pave += pave[i + 1] as u8;
                    verge_count += verge[i + 1] as u8;
                }
                if y > 0 {
                    border_count += road_border[i - w] as u8;
                    ortho_pave += pave[i - w] as u8;
                    verge_count += verge[i - w] as u8;
                }
                if y + 1 < h {
                    border_count += road_border[i + w] as u8;
                    ortho_pave += pave[i + w] as u8;
                    verge_count += verge[i + w] as u8;
                }

                let b_sandwich = (y > 0 && y + 1 < h && road_border[i - w] && road_border[i + w])
                    || (x > 0 && x + 1 < w && road_border[i - 1] && road_border[i + 1]);
                let is_bump = r && (b_sandwich || border_count >= 3);
                bump[i] = is_bump;

                let diag_p = (y > 0 && x > 0 && pave[i - w - 1])
                    || (y > 0 && x + 1 < w && pave[i - w + 1])
                    || (y + 1 < h && x > 0 && pave[i + w - 1])
                    || (y + 1 < h && x + 1 < w && pave[i + w + 1]);
                let is_lonep = p && ortho_pave == 0 && !diag_p;
                lonep[i] = is_lonep;

                let breaks_h = ((x + 1 < w && pave[i + 1]) || (x + 2 < w && pave[i + 2]))
                    && ((x > 0 && pave[i - 1]) || (x > 1 && pave[i - 2]));
                let breaks_v = ((y + 1 < h && pave[i + w]) || (y + 2 < h && pave[i + 2 * w]))
                    && ((y > 0 && pave[i - w]) || (y > 1 && pave[i - 2 * w]));
                let near_r2 = (y + 1 < h && road[i + w])
                    || (y > 0 && road[i - w])
                    || (x + 1 < w && road[i + 1])
                    || (x > 0 && road[i - 1])
                    || (y + 2 < h && road[i + 2 * w])
                    || (y > 1 && road[i - 2 * w])
                    || (x + 2 < w && road[i + 2])
                    || (x > 1 && road[i - 2]);
                let is_mend = v && (breaks_h || breaks_v) && near_r2;
                mend[i] = is_mend;

                let is_pb = p && verge_count >= 3;
                let is_pn = v && ortho_pave >= 3;
                pave_bump[i] = is_pb;
                pave_notch[i] = is_pn;

                any_change |= is_notch || is_bump || is_lonep || is_mend || is_pb || is_pn;
            }
        }

        mark_two_tile_notches(&road_border, &road, w, h, &mut notch);
        mark_two_tile_bumps(&road, &road_border, &road, w, h, &mut bump);
        mark_two_tile_bumps(&pave, &verge, &pave_or_road, w, h, &mut pave_bump);
        mark_two_tile_notches(&verge, &pave, w, h, &mut pave_notch);
        if !any_change {
            any_change = notch.iter().any(|&v| v)
                || bump.iter().any(|&v| v)
                || pave_bump.iter().any(|&v| v)
                || pave_notch.iter().any(|&v| v);
        }

        if !any_change {
            break;
        }

        for y in 0..h {
            let row = y * w;
            for x in 0..w {
                let i = row + x;
                if notch[i] {
                    let src = if y > 0 && road[i - w] {
                        i - w
                    } else if x > 0 && road[i - 1] {
                        i - 1
                    } else if y + 1 < h && road[i + w] {
                        i + w
                    } else {
                        i + 1
                    };
                    let c = read_rgb(ground, src);
                    write_rgb(ground, i, c);
                }
            }
        }

        for y in 0..h {
            let row = y * w;
            for x in 0..w {
                let i = row + x;
                if bump[i] {
                    write_rgb(ground, i, pave_rgb);
                    for (dy, dx) in [(0isize, -1isize), (-1, 0), (0, 1), (1, 0)] {
                        let yy = y as isize + dy;
                        let xx = x as isize + dx;
                        if yy >= 0 && (yy as usize) < h && xx >= 0 && (xx as usize) < w {
                            let ni = (yy as usize) * w + (xx as usize);
                            if pave[ni] {
                                write_rgb(ground, i, pave_rgb);
                                break;
                            }
                            if verge[ni] {
                                let c = read_rgb(ground, ni);
                                write_rgb(ground, i, c);
                            }
                        }
                    }
                }
            }
        }

        for y in 0..h {
            let row = y * w;
            for x in 0..w {
                let i = row + x;
                if lonep[i] {
                    write_rgb(ground, i, medium_grass_rgb);
                    for (dy, dx) in [(0isize, -1isize), (-1, 0), (0, 1), (1, 0)] {
                        let yy = y as isize + dy;
                        let xx = x as isize + dx;
                        if yy >= 0 && (yy as usize) < h && xx >= 0 && (xx as usize) < w {
                            let ni = (yy as usize) * w + (xx as usize);
                            let beside = read_rgb(ground, ni);
                            let bk = pack_rgb(&beside);
                            if bk != pave_key && !asphalt.contains(&bk) {
                                write_rgb(ground, i, beside);
                                break;
                            }
                        }
                    }
                }
            }
        }

        for i in 0..n {
            if mend[i] || pave_notch[i] {
                write_rgb(ground, i, pave_rgb);
            }
        }

        for y in 0..h {
            let row = y * w;
            for x in 0..w {
                let i = row + x;
                if pave_bump[i] {
                    write_rgb(ground, i, medium_grass_rgb);
                    for (dy, dx) in [(0isize, -1isize), (-1, 0), (0, 1), (1, 0)] {
                        let yy = y as isize + dy;
                        let xx = x as isize + dx;
                        if yy >= 0 && (yy as usize) < h && xx >= 0 && (xx as usize) < w {
                            let ni = (yy as usize) * w + (xx as usize);
                            if verge[ni] {
                                let c = read_rgb(ground, ni);
                                write_rgb(ground, i, c);
                                break;
                            }
                        }
                    }
                }
            }
        }
    }
}

pub fn run() {
    let mut r = Reader { inner: io::stdin() };
    if r.take(4) != b"KRS1" {
        die("not a version 1 smooth-roads stream");
    }
    let strips = r.i32();
    if !(1..=1_048_576).contains(&strips) {
        die("invalid smooth-roads strip count");
    }
    let asphalt = read_palette(&mut r, "asphalt");
    let p_raw = r.take(3);
    let pave_rgb = [p_raw[0], p_raw[1], p_raw[2]];
    let mg_raw = r.take(3);
    let medium_grass_rgb = [mg_raw[0], mg_raw[1], mg_raw[2]];
    let verge_pal = read_palette(&mut r, "verge");

    let mut out = io::BufWriter::new(io::stdout());
    for _ in 0..strips {
        let width = r.i32();
        let height = r.i32();
        let out_y0 = r.i32();
        let out_h = r.i32();
        let n = usize::try_from(width)
            .ok()
            .zip(usize::try_from(height).ok())
            .and_then(|(w, h)| w.checked_mul(h));
        let Some(n) = n.filter(|n| *n > 0 && *n <= 33_554_432) else {
            die("invalid smooth-roads strip size");
        };
        let (w, h) = (width as usize, height as usize);
        let oy0 = usize::try_from(out_y0).unwrap_or_else(|_| die("invalid out_y0"));
        let oh = usize::try_from(out_h).unwrap_or_else(|_| die("invalid out_h"));
        if oy0 + oh > h {
            die("invalid smooth-roads output slice");
        }
        let mut ground = r.take(3 * n);
        smooth_strip(&mut ground, w, h, &asphalt, pave_rgb, medium_grass_rgb, &verge_pal);
        out.write_all(b"KRS1").unwrap();
        let start = oy0 * w * 3;
        let end = (oy0 + oh) * w * 3;
        out.write_all(&ground[start..end]).unwrap();
        out.flush().unwrap();
    }
}
