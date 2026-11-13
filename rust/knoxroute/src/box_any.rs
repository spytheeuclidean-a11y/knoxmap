//! O(W * H) separable 2D box dilation for binary masks.
use super::{die, Reader};
use std::io::{self, Write};

pub fn dilate_box(mask: &[u8], width: usize, height: usize, radius: usize) -> Vec<u8> {
    let n = width * height;
    if radius == 0 {
        return mask.iter().map(|&v| u8::from(v != 0)).collect();
    }
    let mut horiz = vec![0u8; n];
    for y in 0..height {
        let row = &mask[y * width..(y + 1) * width];
        let out_row = &mut horiz[y * width..(y + 1) * width];
        let mut count: usize = 0;
        let init_end = (radius + 1).min(width);
        for &v in &row[..init_end] {
            if v != 0 {
                count += 1;
            }
        }
        for x in 0..width {
            out_row[x] = u8::from(count > 0);
            if x >= radius && row[x - radius] != 0 {
                count -= 1;
            }
            let add_idx = x + radius + 1;
            if add_idx < width && row[add_idx] != 0 {
                count += 1;
            }
        }
    }

    let mut out = vec![0u8; n];
    let mut col_counts = vec![0usize; width];
    let init_rows = (radius + 1).min(height);
    for y in 0..init_rows {
        let row = &horiz[y * width..(y + 1) * width];
        for x in 0..width {
            col_counts[x] += row[x] as usize;
        }
    }
    for y in 0..height {
        let out_row = &mut out[y * width..(y + 1) * width];
        for x in 0..width {
            out_row[x] = u8::from(col_counts[x] > 0);
        }
        if y >= radius {
            let sub_row = &horiz[(y - radius) * width..(y - radius + 1) * width];
            for x in 0..width {
                col_counts[x] -= sub_row[x] as usize;
            }
        }
        let add_y = y + radius + 1;
        if add_y < height {
            let add_row = &horiz[add_y * width..(add_y + 1) * width];
            for x in 0..width {
                col_counts[x] += add_row[x] as usize;
            }
        }
    }
    out
}

pub fn run() {
    let mut r = Reader { inner: io::stdin() };
    if r.take(4) != b"KBX1" {
        die("not a version 1 box-any stream");
    }
    let width = r.i32();
    let height = r.i32();
    let radius = r.i32();
    if width <= 0 || height <= 0 || radius < 0 {
        die("invalid box-any dimensions");
    }
    let (w, h, rad) = (width as usize, height as usize, radius as usize);
    let Some(n) = w.checked_mul(h).filter(|&n| n <= 100_000_000) else {
        die("box-any mask too large");
    };
    let mask = r.take(n);
    let dilated = dilate_box(&mask, w, h, rad);
    let mut out = io::BufWriter::new(io::stdout());
    out.write_all(b"KBX1").unwrap();
    out.write_all(&dilated).unwrap();
    out.flush().unwrap();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dilates_single_pixel_with_radius_one() {
        let mut mask = vec![0u8; 25];
        mask[2 * 5 + 2] = 1;
        let out = dilate_box(&mask, 5, 5, 1);
        #[rustfmt::skip]
        let expected = [
            0, 0, 0, 0, 0,
            0, 1, 1, 1, 0,
            0, 1, 1, 1, 0,
            0, 1, 1, 1, 0,
            0, 0, 0, 0, 0,
        ];
        assert_eq!(out, expected);
    }

    #[test]
    fn dilates_corner_with_radius_two() {
        let mut mask = vec![0u8; 16];
        mask[0] = 255;
        let out = dilate_box(&mask, 4, 4, 2);
        #[rustfmt::skip]
        let expected = [
            1, 1, 1, 0,
            1, 1, 1, 0,
            1, 1, 1, 0,
            0, 0, 0, 0,
        ];
        assert_eq!(out, expected);
    }
}
