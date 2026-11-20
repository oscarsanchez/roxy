import { labCertificatesFile } from "./ca-routing";
import { fingerprint, utf8Bytes } from "./fingerprint";
import type { ResultFields } from "./result";

const TIMEOUT_MS = 30000;

// status is the HTTP status, "-28" on a timeout (as the classic app) or "fetch_error"
// when fetch rejects. text is undefined when there was no response.
export type HttpResult = { status: string; text?: string };

// A GET, or a JSON POST when body is given (as the classic HttpTask).
// fetch resolves on 4xx/5xx and has no AbortController, so a timer bounds a stalled request.
export async function httpRequest(url: string, body?: string): Promise<HttpResult> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<HttpResult>(resolve => {
        timer = setTimeout(() => resolve({ status: "-28" }), TIMEOUT_MS);
    });
    // fetch takes one argument: method, headers, body and agent go on a Request.
    const request = new Request(url, {
        ...(body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body }),
        // A CA Routing build trusts the lab's CA with a per-request agent (the SDK's fetch
        // polyfill has no HttpsAgent.setGlobalAgent at runtime).
        ...(labCertificatesFile ? { agent: new HttpsAgent({ certificatesFile: labCertificatesFile }) } : {})
    });
    const response = fetch(request).then(
        async res => ({ status: String(res.status), text: await res.text() }),
        (): HttpResult => ({ status: "fetch_error" })
    );
    try {
        return await Promise.race([response, timeout]);
    } finally {
        clearTimeout(timer);
    }
}

export const textFingerprint = (text: string): Promise<string> => fingerprint(utf8Bytes(text));

// status/bytes/fp, the fields of an HTTP case's result line.
export async function bodyFields(result: HttpResult): Promise<ResultFields> {
    if (result.text === undefined) return [["status", result.status], ["bytes", 0], ["fp", "none"]];
    const bytes = utf8Bytes(result.text);
    return [["status", result.status], ["bytes", bytes.length], ["fp", await fingerprint(bytes)]];
}
