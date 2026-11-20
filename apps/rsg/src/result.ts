export type ResultFields = [string, string | number][];
export type Report = (fields: ResultFields) => void;

// The result line, the grid runner's oracle (same format as the classic app):
//   LABRESULT <case> run=<run id> <key>=<value>...
export function resultLine(caseId: string, runId: string, fields: ResultFields): string {
    return [`LABRESULT ${caseId} run=${runId}`, ...fields.map(([k, v]) => `${k}=${v}`)].join(" ");
}
