//! Woodland pixel processing; Python supplies Pillow's exact polygon masks.
use super::{die, Reader};
use std::io::{self, Write};

fn paint(veg: &mut [u8], land: &mut [u8], masks: &[u8], colours: &[[u8; 3]; 8]) {
    let n = veg.len() / 3;
    let [water, medium, light, dark, scrub, edge, inside, nothing] = *colours;
    for i in 0..n {
        let v = &mut veg[3 * i..3 * i + 3];
        let g = &mut land[3 * i..3 * i + 3];
        if masks[2 * n + i] != 0 {
            v.copy_from_slice(&scrub);
        }
        if masks[i] == 0 || g == water {
            continue;
        }
        let shade = if masks[n + i] != 0 { inside } else { edge };
        if shade == nothing {
            continue;
        }
        v.copy_from_slice(&shade);
        if g == medium || g == light {
            g.copy_from_slice(&dark);
        }
    }
}

pub fn run() {
    let mut r = Reader { inner: io::stdin() };
    if r.take(4) != b"KWD1" {
        die("not a version 1 woodland stream");
    }
    let strips = r.i32();
    if !(1..=1_048_576).contains(&strips) {
        die("invalid woodland strip count");
    }
    let mut out = io::BufWriter::new(io::stdout());
    for _ in 0..strips {
        let (width, height) = (r.i32(), r.i32());
        let n = usize::try_from(width)
            .ok()
            .zip(usize::try_from(height).ok())
            .and_then(|(w, h)| w.checked_mul(h));
        let Some(n) = n.filter(|n| *n > 0 && *n <= 1_048_576) else {
            die("invalid woodland strip size");
        };
        let mut colours = [[0u8; 3]; 8];
        for c in &mut colours {
            c.copy_from_slice(&r.take(3));
        }
        let mut veg = r.take(3 * n);
        let mut land = r.take(3 * n);
        let masks = r.take(3 * n);
        paint(&mut veg, &mut land, &masks, &colours);
        out.write_all(b"KWD1").unwrap();
        out.write_all(&veg).unwrap();
        out.write_all(&land).unwrap();
        out.flush().unwrap();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn scrub_precedes_water_and_empty_forest_shades() {
        let colours = [
            [1; 3], [2; 3], [3; 3], [4; 3], [5; 3], [0; 3], [7; 3], [0; 3],
        ];
        let mut veg = vec![9; 12];
        let mut land = vec![1, 1, 1, 2, 2, 2, 3, 3, 3, 8, 8, 8];
        // Forest, eroded forest, scrub: four pixels in each mask.
        paint(
            &mut veg,
            &mut land,
            &[1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 0, 0],
            &colours,
        );
        assert_eq!(veg, [5, 5, 5, 5, 5, 5, 7, 7, 7, 7, 7, 7]);
        assert_eq!(land, [1, 1, 1, 2, 2, 2, 4, 4, 4, 8, 8, 8]);
    }
}
