import "dotenv/config";
import express from "express";
import { SonioxNodeClient } from "@soniox/node";
import OpenAI from "openai";
import path from "node:path";
import { fileURLToPath } from "node:url";

const { SONIOX_API_KEY, VSELLM_API_KEY } = process.env;

if (!SONIOX_API_KEY || !VSELLM_API_KEY) {
  throw new Error(
    "Missing required environment variables: SONIOX_API_KEY and VSELLM_API_KEY",
  );
}

const app = express();
const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const publicDir = path.join(projectRoot, "public");
const port = Number.parseInt(process.env.PORT ?? "3001", 10);

app.use(express.json());
app.use(express.static(publicDir));

// -------------------------
// SONIOX
// -------------------------

const soniox = new SonioxNodeClient({ api_key: SONIOX_API_KEY });

const temporaryKeyRequests = new Map();
const temporaryKeyWindowMs = 60_000;
const temporaryKeyLimit = 10;

function temporaryKeyRateLimit(req, res, next) {
  const clientId = req.ip ?? req.socket.remoteAddress ?? "unknown";
  const now = Date.now();
  const current = temporaryKeyRequests.get(clientId);

  if (!current || now - current.windowStartedAt >= temporaryKeyWindowMs) {
    temporaryKeyRequests.set(clientId, { count: 1, windowStartedAt: now });
    next();
    return;
  }

  if (current.count >= temporaryKeyLimit) {
    const retryAfterSeconds = Math.ceil(
      (temporaryKeyWindowMs - (now - current.windowStartedAt)) / 1000,
    );
    res.set("Retry-After", String(retryAfterSeconds));
    res.status(429).json({ error: "Too many temporary key requests" });
    return;
  }

  current.count += 1;
  next();
}

// Временный ключ для Soniox
app.get("/tts-tmp-key", temporaryKeyRateLimit, async (_req, res) => {
  try {
    const { api_key, expires_at } =
      await soniox.auth.createTemporaryKey({
        usage_type: "tts_rt",
        expires_in_seconds: 300,
      });

    res.set("Cache-Control", "no-store");
    res.json({ api_key, expires_at });
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: "Temporary key error" });
  }
});

// Генерация речи
app.post("/tts", async (req, res) => {
  try {
    const audio = await soniox.tts.generate({
      text: req.body.text,
      voice: "Nina",
      model: "tts-rt-v2",
      language: "ru",
      audio_format: "wav",
    });

    res.type("audio/wav");
    res.send(Buffer.from(audio));
  } catch (err) {
    console.error(err);
    res.status(500).send("TTS error");
  }
});

// -------------------------
// VSELLM / LLM
// -------------------------

const llm = new OpenAI({
  apiKey: VSELLM_API_KEY,
  baseURL: "https://api.vsellm.ru/v1",
});

app.post("/chat", async (req, res) => {
  try {
    const userMessages = req.body.messages || [];

    const response = await llm.chat.completions.create({
      model: "google/gemini-2.5-flash",

      messages: [
        {
          role: "system",
          content:
            "Ты собеседник в учебном диалоговом тренажёре. Отвечай естественно, кратко и разговорно на русском языке. Не используй markdown.",
        },
        ...userMessages,
      ],

      temperature: 0.7,
      max_tokens: 300,
    });

    const reply =
      response.choices[0]?.message?.content || "";

    res.json({ reply });
  } catch (err) {
    console.error(err);

    res.status(500).json({
      error: err instanceof Error ? err.message : "LLM error",
    });
  }
});

// -------------------------
// START
// -------------------------

app.listen(port, () => {
  console.log(`Server: http://localhost:${port}`);
});
