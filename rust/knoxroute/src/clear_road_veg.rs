//! Clear vegetation on road, sidewalk, rail, and water pixels.
use super::{die, Reader};
use std::io::{self, Write};

#[inline]
fn pack_rgb(rgb: &[u8]) -> u32 {
    ((rgb[0] as u32) << 16) | ((rgb[1] as u32) << 8) | (rgb[2] as u32)
}

fn read_palette(r: &mut Reader<impl io::Read>, label: &str) -> Vec<u32> {
    let count = r.i32();
    if !(0..=4096).contains(&count) {
        die(&format!("invalid {label} palette size"));
    }
    let raw = r.take(3 * count as usize);
    raw.chunks_exact(3).map(pack_rgb).collect()
}

pub fn clear_strip(
    veg: &mut [u8],
    land: &[u8],
    road_colours: &[u32],
    veg_colours: &[u32],
    veg_nothing: [u8; 3],
) {
    for (v, g) in veg.chunks_exact_mut(3).zip(land.chunks_exact(3)) {
        let gp = pack_rgb(g);
        if !road_colours.contains(&gp) {
            continue;
        }
        let vp = pack_rgb(v);
        if veg_colours.contains(&vp) {
            v.copy_from_slice(&veg_nothing);
        }
    }
}

pub fn run() {
    let mut r = Reader { inner: io::stdin() };
    if r.take(4) != b"KRV1" {
        die("not a version 1 clear-road-veg stream");
    }
    let strips = r.i32();
    if !(1..=1_048_576).contains(&strips) {
        die("invalid clear-road-veg strip count");
    }
    let road_colours = read_palette(&mut r, "road");
    let veg_colours = read_palette(&mut r, "veg");
    let nothing_raw = r.take(3);
    let veg_nothing = [nothing_raw[0], nothing_raw[1], nothing_raw[2]];

    let mut out = io::BufWriter::new(io::stdout());
    for _ in 0..strips {
        let (width, height) = (r.i32(), r.i32());
        let n = usize::try_from(width)
            .ok()
            .zip(usize::try_from(height).ok())
            .and_then(|(w, h)| w.checked_mul(h));
        let Some(n) = n.filter(|n| *n > 0 && *n <= 4_194_304) else {
            die("invalid clear-road-veg strip size");
        };
        let mut veg = r.take(3 * n);
        let land = r.take(3 * n);
        clear_strip(&mut veg, &land, &road_colours, &veg_colours, veg_nothing);
        out.write_all(b"KRV1").unwrap();
        out.write_all(&veg).unwrap();
        out.flush().unwrap();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clears_only_veg_on_road_pixels() {
        let road = [pack_rgb(&[10, 10, 10]), pack_rgb(&[20, 20, 20])];
        let veg_pal = [pack_rgb(&[1, 2, 3]), pack_rgb(&[4, 5, 6])];
        let nothing = [0, 0, 0];
        let mut veg = vec![
            1, 2, 3,   // on road + is veg -> cleared
            9, 9, 9,   // on road + not veg -> kept
            4, 5, 6,   // off road + is veg -> kept
            1, 2, 3,   // on road2 + is veg -> cleared
        ];
        let land = [
            10, 10, 10,
            10, 10, 10,
            99, 99, 99,
            20, 20, 20,
        ];
        clear_strip(&mut veg, &land, &road, &veg_pal, nothing);
        assert_eq!(
            veg,
            [0, 0, 0, 9, 9, 9, 4, 5, 6, 0, 0, 0]
        );
    }
}
