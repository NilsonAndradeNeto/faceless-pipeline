# Faceless Pipeline — Shorts de História + Mistérios (PT/ES)

Pipeline automático que pesquisa, escreve, narra, monta e publica Shorts verticais
(YouTube Shorts, TikTok e Reels) em português e espanhol.

> 🚧 Em construção. Este README será completado na FASE 8.

## Fluxo

```
tema (niches.yaml) → roteiro 45–60s → revisão humana (localhost:3200)
→ narração (ElevenLabs / XTTS) → b-roll vertical (Pexels/Pixabay/Pollinations)
→ FFmpeg 1080x1920 + legenda palavra por palavra → publicação
```

## Estrutura

- `config/` — temas, vozes, canais e limites de segurança do PC
- `agents/` — agentes de LLM (pesquisa, roteiro, planejamento visual, análise)
- `pipeline/` — narração, b-roll, montagem e publicação
- `review_app/` — painel de aprovação de roteiros
- `storage/` — tudo que é gerado (não vai pro git)
