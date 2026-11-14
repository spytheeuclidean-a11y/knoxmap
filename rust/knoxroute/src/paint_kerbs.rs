//! Paint real road kerbs onto the vegetation/detail layer in strips.
use super::{die, Reader};
use std::io::{self, Write};

const W: u8 = 1;
const N: u8 = 2;
const S: u8 = 4;
const E: u8 = 8;
const NW: u8 = W | N;
const SW: u8 = S | W;
const NE: u8 = N | E;
const SE: u8 = S | E;

#[inline]
fn pack_rgb(rgb: &[u8]) -> u32 {
    ((rgb[0] as u32) << 16) | ((rgb[1] as u32) << 8) | (rgb[2] as u32)
}

#[inline]
fn read_palette(r: &mut Reader<impl io::Read>, label: &str) -> Vec<u32> {
    let count = r.i32();
    if !(0..=4096).contains(&count) {
        die(&format!("invalid {label} palette size"));
    }
    let raw = r.take(3 * count as usize);
    raw.chunks_exact(3).map(pack_rgb).collect()
}

#[inline]
fn run3(a: u8, a2: u8, b: u8, b2: u8, x0: u8, x1: u8, x2: u8) -> bool {
    let ia = a == x0 || a == x1 || a == x2;
    let ia2 = a2 == x0 || a2 == x1 || a2 == x2;
    let ib = b == x0 || b == x1 || b == x2;
    let ib2 = b2 == x0 || b2 == x1 || b2 == x2;
    (ia && ib) || (ia && ia2) || (ib && ib2)
}

pub fn paint_strip(
    ground: &[u8],
    veg: &mut [u8],
    w: usize,
    h: usize,
    out_y0: usize,
    out_h: usize,
    asphalt: &[u32],
    pave_rgb: [u8; 3],
    kerb_colours: [[u8; 3]; 8],
) {
    let n = w * h;
    let pave_key = pack_rgb(&pave_rgb);
    let mut road = vec![false; n];
    let mut sides = vec![0u8; n];

    for i in 0..n {
        road[i] = asphalt.contains(&pack_rgb(&ground[i * 3..i * 3 + 3]));
    }

    for y in 0..h {
        let row = y * w;
        for x in 0..w {
            let i = row + x;
            if pack_rgb(&ground[i * 3..i * 3 + 3]) != pave_key {
                continue;
            }
            let mut bits = 0u8;
            if x > 0 && road[i - 1] {
                bits |= W;
            }
            if y > 0 && road[i - w] {
                bits |= N;
            }
            if y + 1 < h && road[i + w] {
                bits |= S;
            }
            if x + 1 < w && road[i + 1] {
                bits |= E;
            }
            sides[i] = bits;
        }
    }

    let side_at = |yy: isize, xx: isize| -> u8 {
        if yy >= 0 && (yy as usize) < h && xx >= 0 && (xx as usize) < w {
            sides[(yy as usize) * w + (xx as usize)]
        } else {
            0
        }
    };

    for dy in 0..out_h {
        let y = out_y0 + dy;
        let yi = y as isize;
        let out_row = dy * w;
        for x in 0..w {
            let s = sides[y * w + x];
            if s == 0 {
                continue;
            }
            let xi = x as isize;
            let keep = match s {
                N => run3(
                    side_at(yi, xi - 1),
                    side_at(yi, xi - 2),
                    side_at(yi, xi + 1),
                    side_at(yi, xi + 2),
                    N,
                    NW,
                    NE,
                ),
                S => run3(
                    side_at(yi, xi - 1),
                    side_at(yi, xi - 2),
                    side_at(yi, xi + 1),
                    side_at(yi, xi + 2),
                    S,
                    SW,
                    SE,
                ),
                W => run3(
                    side_at(yi - 1, xi),
                    side_at(yi - 2, xi),
                    side_at(yi + 1, xi),
                    side_at(yi + 2, xi),
                    W,
                    NW,
                    SW,
                ),
                E => run3(
                    side_at(yi - 1, xi),
                    side_at(yi - 2, xi),
                    side_at(yi + 1, xi),
                    side_at(yi + 2, xi),
                    E,
                    NE,
                    SE,
                ),
                NW => side_at(yi, xi + 1) == N && side_at(yi + 1, xi) == W,
                NE => side_at(yi, xi - 1) == N && side_at(yi + 1, xi) == E,
                SW => side_at(yi, xi + 1) == S && side_at(yi - 1, xi) == W,
                SE => side_at(yi, xi - 1) == S && side_at(yi - 1, xi) == E,
                _ => false,
            };
            if !keep {
                continue;
            }
            let slot = match s {
                W => 0,
                N => 1,
                S => 2,
                E => 3,
                NW => 4,
                SW => 5,
                NE => 6,
                SE => 7,
                _ => continue,
            };
            let voff = (out_row + x) * 3;
            if veg[voff] == 0 && veg[voff + 1] == 0 && veg[voff + 2] == 0 {
                let rgb = kerb_colours[slot];
                veg[voff] = rgb[0];
                veg[voff + 1] = rgb[1];
                veg[voff + 2] = rgb[2];
            }
        }
    }
}

pub fn run() {
    let mut r = Reader { inner: io::stdin() };
    if r.take(4) != b"KRK1" {
        die("not a version 1 paint-kerbs stream");
    }
    let strips = r.i32();
    if !(1..=1_048_576).contains(&strips) {
        die("invalid paint-kerbs strip count");
    }
    let asphalt = read_palette(&mut r, "asphalt");
    let p_raw = r.take(3);
    let pave_rgb = [p_raw[0], p_raw[1], p_raw[2]];
    let k_raw = r.take(24);
    let mut kerb_colours = [[0u8; 3]; 8];
    for (idx, chunk) in k_raw.chunks_exact(3).enumerate() {
        kerb_colours[idx] = [chunk[0], chunk[1], chunk[2]];
    }

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
            die("invalid paint-kerbs strip size");
        };
        let (w, h) = (width as usize, height as usize);
        let oy0 = usize::try_from(out_y0).unwrap_or_else(|_| die("invalid out_y0"));
        let oh = usize::try_from(out_h).unwrap_or_else(|_| die("invalid out_h"));
        if oy0 + oh > h {
            die("invalid paint-kerbs output slice");
        }
        let ground = r.take(3 * n);
        let mut veg = r.take(3 * w * oh);
        paint_strip(
            &ground,
            &mut veg,
            w,
            h,
            oy0,
            oh,
            &asphalt,
            pave_rgb,
            kerb_colours,
        );
        out.write_all(b"KRK1").unwrap();
        out.write_all(&veg).unwrap();
        out.flush().unwrap();
    }
}
