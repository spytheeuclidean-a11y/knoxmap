//! Just enough BMP to read a grey picture: uncompressed, 8 or 24 bits.
//!
//! The zombie spawn map is one of these, one pixel to 10 x 10 tiles.

use crate::spawn::Grey;

pub struct GreyImage {
    pub width: usize,
    pub height: usize,
    pub pixels: Vec<u8>,
}

impl GreyImage {
    pub fn view(&self) -> Grey<'_> {
        Grey { width: self.width, height: self.height, pixels: &self.pixels }
    }
}

fn le16(d: &[u8], o: usize) -> Result<u16, String> {
    d.get(o..o + 2).map(|b| u16::from_le_bytes([b[0], b[1]])).ok_or_else(|| "BMP is cut short".to_string())
}

fn le32(d: &[u8], o: usize) -> Result<u32, String> {
    d.get(o..o + 4).map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]])).ok_or_else(|| "BMP is cut short".to_string())
}

pub fn read_grey(d: &[u8]) -> Result<GreyImage, String> {
    if d.get(..2) != Some(b"BM") {
        return Err("not a BMP".into());
    }
    let offset = le32(d, 10)? as usize;
    let size = le32(d, 14)? as usize;
    let width = le32(d, 18)? as i32;
    let height = le32(d, 22)? as i32;
    let bits = le16(d, 28)?;
    let compression = le32(d, 30)?;
    if size < 40 || compression != 0 || width <= 0 || height == 0 {
        return Err("only plain uncompressed BMP files are read".into());
    }
    let (w, h, bottom_up) = (width as usize, height.unsigned_abs() as usize, height > 0);
    if w.checked_mul(h).map_or(true, |n| n > 1 << 28) {
        return Err("BMP is too large for a spawn map".into());
    }
    let (bpp, palette): (usize, Vec<u8>) = match bits {
        24 => (3, Vec::new()),
        8 => {
            let start = 14 + size;
            let mut p = Vec::with_capacity(256);
            for i in 0..256 {
                // palette entries are B, G, R, unused; grey of the entry
                let e = d.get(start + 4 * i..start + 4 * i + 4).ok_or("BMP palette is cut short")?;
                p.push(grey(e[2], e[1], e[0]));
            }
            (1, p)
        }
        b => return Err(format!("{b}-bit BMP is not read")),
    };
    let stride = (w * bpp + 3) / 4 * 4;
    if d.len() < offset + stride * h {
        return Err("BMP is cut short".into());
    }
    let mut pixels = vec![0u8; w * h];
    for row in 0..h {
        let src_row = if bottom_up { h - 1 - row } else { row };
        let line = &d[offset + src_row * stride..offset + src_row * stride + w * bpp];
        for x in 0..w {
            pixels[row * w + x] = if bpp == 1 {
                palette[line[x] as usize]
            } else {
                grey(line[3 * x + 2], line[3 * x + 1], line[3 * x])
            };
        }
    }
    Ok(GreyImage { width: w, height: h, pixels })
}

/// Equal channels are the grey itself; anything else is the usual weighting.
fn grey(r: u8, g: u8, b: u8) -> u8 {
    if r == g && g == b {
        r
    } else {
        ((r as u32 * 299 + g as u32 * 587 + b as u32 * 114) / 1000) as u8
    }
}
