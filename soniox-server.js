import express from "express";
import { SonioxNodeClient } from "@soniox/node";
import OpenAI from "openai";

const app = express();

app.use(express.json());
app.use(express.static("."));

// -------------------------
// SONIOX
// -------------------------

const soniox = new SonioxNodeClient();

// Временный ключ для Soniox
app.get("/tts-tmp-key", async (_req, res) => {
  try {
    const { api_key, expires_at } =
      await soniox.auth.createTemporaryKey({
        usage_type: "tts_rt",
        expires_in_seconds: 300,
      });

    res.json({ api_key, expires_at });
  } catch (err) {
    console.error(err);
    res.status(500).json({
      error: err instanceof Error ? err.message : "Temporary key error",
    });
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
  apiKey: process.env.VSELLM_API_KEY,
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

app.listen(3001, () => {
  console.log("Server: http://localhost:3001");
});