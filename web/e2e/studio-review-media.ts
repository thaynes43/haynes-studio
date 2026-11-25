import { createHash } from "node:crypto";
import type { Browser, Route } from "@playwright/test";

function media(body: Buffer, mime: string) {
  return { body, mime, hash: createHash("sha256").update(body).digest("hex") };
}

export type TestMedia = ReturnType<typeof media>;
export type ReviewMedia = Record<"proxy" | "master" | "olderMaster" | "photo" | "voice", TestMedia>;

export async function generateReviewMedia(browser: Browser): Promise<ReviewMedia> {
  const page = await browser.newPage();
  try {
    const { proxy, master, olderMaster, photo } = await page.evaluate(async () => {
      async function video(width: number, height: number) {
        const canvas = Object.assign(document.createElement("canvas"), { width, height });
        const ctx = canvas.getContext("2d")!;
        const stream = canvas.captureStream(24);
        const recorder = new MediaRecorder(stream, { mimeType: "video/mp4;codecs=avc1.42001f" });
        const chunks: Blob[] = [];
        recorder.ondataavailable = (event) => chunks.push(event.data);
        const stopped = new Promise<void>((resolve) => { recorder.onstop = () => resolve(); });
        recorder.start();
        // Drive genuine frame changes for a short, disposable clip.
        for (let frame = 0; frame < 12; frame++) {
          ctx.fillStyle = frame % 2 ? "#174832" : "#1c262c";
          ctx.fillRect(0, 0, width, height);
          await new Promise<void>((resolve) => setTimeout(resolve, 1000 / 24));
        }
        recorder.stop();
        await stopped;
        for (const track of stream.getTracks()) track.stop();
        return {
          bytes: [...new Uint8Array(await new Blob(chunks).arrayBuffer())],
          photo: canvas.toDataURL("image/png").split(",")[1],
        };
      }
      const proxy = await video(64, 96);
      const master = await video(96, 144);
      const olderMaster = await video(80, 120);
      return { proxy: proxy.bytes, master: master.bytes, olderMaster: olderMaster.bytes, photo: master.photo };
    });
    // A short silent mono PCM WAV for the board's voice player.
    const samples = 1600;
    const wave = Buffer.alloc(44 + samples * 2);
    wave.write("RIFF", 0);
    wave.writeUInt32LE(wave.length - 8, 4);
    wave.write("WAVEfmt ", 8);
    wave.writeUInt32LE(16, 16);
    wave.writeUInt16LE(1, 20);
    wave.writeUInt16LE(1, 22);
    wave.writeUInt32LE(8000, 24);
    wave.writeUInt32LE(16000, 28);
    wave.writeUInt16LE(2, 32);
    wave.writeUInt16LE(16, 34);
    wave.write("data", 36);
    wave.writeUInt32LE(samples * 2, 40);
    return {
      proxy: media(Buffer.from(proxy), "video/mp4"),
      master: media(Buffer.from(master), "video/mp4"),
      olderMaster: media(Buffer.from(olderMaster), "video/mp4"),
      photo: media(Buffer.from(photo, "base64"), "image/png"),
      voice: media(wave, "audio/wav"),
    };
  } finally {
    await page.close();
  }
}

export function mediaResponse(route: Route, file: TestMedia) {
  const request = route.request();
  const { range, "if-range": ifRange } = request.headers();
  const etag = `"${file.hash}"`;
  const size = file.body.length;
  const headers: Record<string, string> = {
    "accept-ranges": "bytes", etag, "cache-control": "private, no-store",
    "content-length": String(size), "content-type": file.mime,
  };
  const match = (!ifRange || ifRange === etag) && /^bytes=(?:(\d+)-(\d*)|-(\d+))$/.exec(range ?? "");
  const head = request.method() === "HEAD";
  if (match) {
    const start = match[3] ? Math.max(0, size - Number(match[3])) : Number(match[1]);
    const end = match[2] ? Number(match[2]) : size - 1;
    if (start >= size && (match[3] || !match[2] || end >= start)) {
      return { status: 416, headers: { ...headers, "content-range": `bytes */${size}`, "content-length": "0" } };
    }
    if (start <= end) {
      const last = Math.min(end, size - 1);
      headers["content-range"] = `bytes ${start}-${last}/${size}`;
      headers["content-length"] = String(last - start + 1);
      return { status: 206, headers, body: head ? undefined : file.body.subarray(start, last + 1) };
    }
  }
  return { status: 200, headers, body: head ? undefined : file.body };
}
