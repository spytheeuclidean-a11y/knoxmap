use knoxlots::chunkdata::ChunkData;
use knoxlots::header::{Header, Room, CHUNK_VALUES};
use knoxlots::pack::{encode, expand, Pack, Rec};

fn header() -> Header {
    Header {
        version: 1,
        tiles: vec!["blends_natural_01_0".into(), "walls_exterior_house_01_0".into()],
        field_a: 8,
        field_b: 8,
        min_z: 0,
        max_z: 2,
        rooms: vec![Room {
            name: "bedroom".into(),
            z: 0,
            rects: vec![[22, 1, 3, 3], [30, 4, 2, 2]],
            objects: vec![[4, 102, 184]],
        }],
        buildings: vec![vec![0], vec![]],
        chunk_values: (0..CHUNK_VALUES).map(|i| (i % 3) as u8).collect(),
    }
}

fn pack() -> Pack {
    let chunk = vec![
        Rec::Skip(70),
        Rec::Square(vec![0xFFFF_FFFF, 1]),
        Rec::Square(vec![3, 0, 1]),
        Rec::Skip(120),
    ];
    Pack { version: 1, chunks: vec![chunk.clone(), chunk, vec![Rec::Skip(192)]] }
}

#[test]
fn header_round_trips() {
    let h = header();
    let bytes = h.write();
    assert_eq!(Header::parse(&bytes).unwrap(), h);
    assert_eq!(Header::parse(&bytes).unwrap().write(), bytes);
}

#[test]
fn pack_round_trips_and_rebuilds_from_squares() {
    let p = pack();
    let bytes = p.write();
    let back = Pack::parse(&bytes).unwrap();
    assert_eq!(back, p);
    assert_eq!(back.write(), bytes);
    for c in &back.chunks {
        assert_eq!(&encode(&expand(c)), c);
    }
}

#[test]
fn chunkdata_round_trips() {
    let mut bytes = vec![0u8, 1];
    bytes.extend((0..1024).map(|i| (i % 5) as u8));
    bytes.extend([7u8; 64]);
    let c = ChunkData::parse(&bytes).unwrap();
    assert_eq!(c.blocks.len(), 1);
    assert_eq!(c.write(), bytes);
    assert!(ChunkData::parse(&bytes[..bytes.len() - 1]).is_err());
}

#[test]
fn damaged_files_are_errors_not_panics() {
    let h = header().write();
    let p = pack().write();
    for len in 0..h.len() {
        let _ = Header::parse(&h[..len]);
    }
    for len in 0..p.len() {
        let _ = Pack::parse(&p[..len]);
    }
    // A count that promises far more than the file holds.
    let mut huge = h.clone();
    huge[8..12].copy_from_slice(&u32::MAX.to_le_bytes());
    assert!(Header::parse(&huge).is_err());
    let mut bad_offset = p.clone();
    bad_offset[12..20].copy_from_slice(&u64::MAX.to_le_bytes());
    assert!(Pack::parse(&bad_offset).is_err());
    // Bytes that are not a file of either kind.
    assert!(Header::parse(b"nope").is_err());
    assert!(Pack::parse(&[0u8; 40]).is_err());
}
