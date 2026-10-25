# AGENT.md

## Project Name

Malva Voice AI

## Objective

Build a voice-enabled AI assistant that runs in the browser and uses a remote Ollama server.

The AI model is hosted on VPS.

The frontend runs on the local laptop.

Users can speak to the AI and receive spoken responses.

---

## AI Endpoint

Remote Ollama Server:

http://34.59.149.93:11434

Endpoint:

POST /api/generate

Model:

lfm2.5:latest

Request:

{
"model": "lfm2.5:latest",
"prompt": "<user message>",
"stream": true
}

---

## Technology Stack

Backend:

* FastAPI

Frontend:

* HTML
* CSS
* Vanilla JavaScript

Voice Input:

* Web Speech API
* SpeechRecognition

Voice Output:

* SpeechSynthesis API

AI:

* Remote Ollama VPS

---

## Application Flow

User clicks microphone button.

Browser records voice.

SpeechRecognition converts voice to text.

Frontend sends text to FastAPI.

FastAPI sends prompt to Ollama VPS.

Ollama returns response.

Frontend displays response.

SpeechSynthesis reads the response aloud.

---

## Required Features

### Chat

* Text input
* Send button
* Chat history

### Voice Input

* Microphone button
* Start listening
* Stop listening
* Auto-fill recognized text

### Voice Output

* Read AI response aloud
* Auto-play response
* Stop speaking button

### UI

* Dark mode
* Responsive layout
* ChatGPT-like appearance
* Mobile friendly

---

## Folder Structure

project/

├── app.py
├── requirements.txt
├── services/
│   └── ollama.py
├── templates/
│   └── index.html
├── static/
│   ├── app.js
│   └── style.css
├── .env
└── AGENT.md

---

## Environment Variables

OLLAMA_URL=http://34.59.149.93:11434/api/generate

OLLAMA_MODEL=lfm2.5:latest

---

## Backend Requirements

Create POST /chat

Request:

{
"message": "Halo"
}

Response:

{
"response": "Halo juga"
}

Backend must only proxy requests to Ollama.

No local AI processing.

---

## Frontend Requirements

Implement:

* Chat area
* Text input
* Send button
* Microphone button
* Speak response button

Use:

window.SpeechRecognition

or

window.webkitSpeechRecognition

for speech recognition.

Use:

window.speechSynthesis

for text-to-speech.

---

## Success Criteria

User can:

1. Open website.
2. Click microphone.
3. Speak.
4. Voice becomes text.
5. Text is sent to Ollama VPS.
6. AI responds.
7. AI response is spoken aloud.

No local Ollama required.

No Whisper required.

No Piper required.

All AI generation runs on VPS.
