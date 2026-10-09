//! The zombie intensity bytes at the end of a `.lotheader`.
//!
//! Found by experiment: WorldEd compiled small maps that differ in one thing
//! (a road, a house) and every one of the 1024 bytes, in every cell, equals the
//! floor of the mean of the map's `_ZombieSpawnMap.bmp` (a grey picture, one pixel
//! to 10 x 10 tiles) over the chunk's 8 x 8 tiles; pixels outside the picture count
//! as 0. Compared with max, min, rounded mean, most common value and the
//! middle tile: only the floored mean matched all 16,384 chunks tested.
//!
//! The bytes are stored x-major: index = chunk_x * 32 + chunk_y within the cell.

pub const CHUNK: usize = 8;
pub const PIXEL: usize = 10;
pub const CHUNKS_PER_SIDE: usize = 32;

/// A grey picture: `width * height` bytes, row by row.
pub struct Grey<'a> {
    pub width: usize,
    pub height: usize,
    pub pixels: &'a [u8],
}

impl Grey<'_> {
    fn at(&self, tile_x: i64, tile_y: i64) -> u32 {
        if tile_x < 0 || tile_y < 0 {
            return 0;
        }
        let (px, py) = (tile_x as usize / PIXEL, tile_y as usize / PIXEL);
        if px >= self.width || py >= self.height {
            return 0;
        }
        self.pixels[py * self.width + px] as u32
    }

    /// The intensity byte for the chunk at (`chunk_x`, `chunk_y`), counted in chunks
    /// from the picture's top-left corner (the world's origin).
    pub fn chunk_intensity(&self, chunk_x: i64, chunk_y: i64) -> u8 {
        let mut sum = 0u32;
        for dy in 0..CHUNK as i64 {
            for dx in 0..CHUNK as i64 {
                sum += self.at(chunk_x * CHUNK as i64 + dx, chunk_y * CHUNK as i64 + dy);
            }
        }
        (sum / (CHUNK * CHUNK) as u32) as u8
    }
}

/// Index of a chunk within a cell's 1024 bytes.
pub fn index(local_x: usize, local_y: usize) -> usize {
    local_x * CHUNKS_PER_SIDE + local_y
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn floors_the_mean_and_treats_outside_as_zero() {
        // 2 x 2 pixels = 20 x 20 tiles; the top-left pixel is 3, the rest 0.
        let g = Grey { width: 2, height: 2, pixels: &[3, 0, 0, 0] };
        // Chunk (0,0) covers tiles 0..8: all inside the 3-pixel -> 3.
        assert_eq!(g.chunk_intensity(0, 0), 3);
        // Chunk (1,0) covers tiles 8..16 x 0..8: columns 8,9 are 3, 10..15 are 0 -> 3*2*8/64 = 0.75 -> 0.
        assert_eq!(g.chunk_intensity(1, 0), 0);
        // Beyond the picture, and before it.
        assert_eq!(g.chunk_intensity(50, 50), 0);
        assert_eq!(g.chunk_intensity(-1, -1), 0);
        assert_eq!(index(2, 5), 69);
    }
}
