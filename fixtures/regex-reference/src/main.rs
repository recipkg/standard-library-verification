use regex::Regex;
use std::{env, process};

fn json_string(value: &str) -> String {
    let mut out = String::from("\"");
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            ch if ch < '\u{20}' => out.push_str(&format!("\\u{:04x}", ch as u32)),
            ch => out.push(ch),
        }
    }
    out.push('"');
    out
}

fn captures_json(re: &Regex, haystack: &str) -> String {
    let names = re
        .capture_names()
        .map(|name| name.map(json_string).unwrap_or_else(|| "null".to_owned()))
        .collect::<Vec<_>>()
        .join(",");
    let captures = re
        .captures_iter(haystack)
        .map(|captures| {
            (0..captures.len())
                .map(|index| {
                    captures
                        .get(index)
                        .map(|matched| format!("[{},{}]", matched.start(), matched.end()))
                        .unwrap_or_else(|| "null".to_owned())
                })
                .collect::<Vec<_>>()
                .join(",")
        })
        .map(|groups| format!("[{groups}]"))
        .collect::<Vec<_>>()
        .join(",");
    format!("{{\"names\":[{names}],\"captures\":[{captures}]}}")
}

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
    if args.len() == 4 && args[1] == "--captures" {
        match Regex::new(&args[2]) {
            Ok(re) => println!("{}", captures_json(&re, &args[3])),
            Err(_) => {
                println!("{{\"error\":\"compile\"}}");
                process::exit(2);
            }
        }
        return;
    }
    if args.len() == 5 && (args[1] == "--replace-first" || args[1] == "--replace-all") {
        match Regex::new(&args[2]) {
            Ok(re) => {
                let replaced = if args[1] == "--replace-first" {
                    re.replace(&args[3], args[4].as_str())
                } else {
                    re.replace_all(&args[3], args[4].as_str())
                };
                println!("{{\"text\":{}}}", json_string(&replaced));
            }
            Err(_) => {
                println!("{{\"error\":\"compile\"}}");
                process::exit(2);
            }
        }
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
