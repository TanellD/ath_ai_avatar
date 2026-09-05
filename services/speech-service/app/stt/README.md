# STT primitives

Этот каталог содержит provider-neutral контракты, bounded PCM buffer, mock и
realtime Soniox provider. Gateway подключается к `/stt/stream`, передаёт
первым JSON `open`, затем binary PCM и завершает turn JSON `finalize`.
GigaAM и automatic failover появятся следующими этапами по
[`docs/voice-input-plan.md`](../../../../../docs/voice-input-plan.md).

Канонический вход: mono PCM16LE, 16 kHz. Dialogue `gen_id`, commit и Turn
Intelligence принадлежат gateway, а не STT provider.
