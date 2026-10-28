use regex::Regex;
use std::{env, process};

fn decode_hex(input: &str) -> Option<Vec<u8>> {
    let (pairs, remainder) = input.as_bytes().as_chunks::<2>();
    let bytes = pairs
        .iter()
        .map(|pair| {
            let high = (pair[0] as char).to_digit(16)?;
            let low = (pair[1] as char).to_digit(16)?;
            Some(((high << 4) | low) as u8)
        })
        .collect::<Option<Vec<_>>>()?;
    remainder.is_empty().then_some(bytes)
}

fn main() {
    let args: Vec<String> = env::args().collect();
    if args.len() == 2 && args[1] == "--version" {
        println!("recipkg regex probe 0.2.0 (regex 1.13.0)");
        return;
    }
    if args.len() == 4 && args[1] == "--bytes" {
        let Some(bytes) = decode_hex(&args[3]) else {
            eprintln!("invalid hexadecimal input");
            process::exit(64);
        };
        match regex::bytes::Regex::new(&args[2]) {
            Ok(re) => {
                let pairs: Vec<String> = re
                    .find_iter(&bytes)
                    .map(|m| format!("[{},{}]", m.start(), m.end()))
                    .collect();
                println!("{{\"matches\":[{}]}}", pairs.join(","));
            }
            Err(_) => {
                println!("{{\"error\":\"compile\"}}");
                process::exit(2);
            }
        }
        return;
    }
    if args.len() != 3 {
        eprintln!("expected PATTERN TEXT");
        process::exit(64);
    }
    match Regex::new(&args[1]) {
        Ok(re) => {
            let pairs: Vec<String> = re
                .find_iter(&args[2])
                .map(|m| format!("[{},{}]", m.start(), m.end()))
                .collect();
            println!("{{\"matches\":[{}]}}", pairs.join(","));
        }
        Err(_) => {
            println!("{{\"error\":\"compile\"}}");
            process::exit(2);
        }
    }
}
