import { subtle } from "@roku-sdk/runtime/crypto";

// The runtime has no TextEncoder.
export function utf8Bytes(text: string): Uint8Array {
    const out: number[] = [];
    for (const ch of text) {
        const c = ch.codePointAt(0)!;
        if (c < 0x80) out.push(c);
        else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
        else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
        else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    return new Uint8Array(out);
}

// The fp in result lines: the first 12 hex digits of the SHA-1 (same as the classic app).
export async function fingerprint(bytes: Uint8Array): Promise<string> {
    const digest = new Uint8Array(await subtle.digest("SHA-1", bytes.buffer as ArrayBuffer));
    return Array.from(digest.slice(0, 6), b => b.toString(16).padStart(2, "0")).join("");
}
