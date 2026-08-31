let voiceListening = false;
let recognition = null;

function initVoice() {
    setupSpeechRecognition();
    setupTextFallback();
}

function setupSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
        document.getElementById('voice-mic-btn').style.display = 'none';
        document.getElementById('voice-status').textContent = 'Speech recognition not supported in this browser. Use text input.';
        return;
    }

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onresult = (event) => {
        const transcript = Array.from(event.results)
            .map(r => r[0].transcript)
            .join('');
        document.getElementById('voice-text-input').value = transcript;

        if (event.results[0].isFinal) {
            processVoiceQuery(transcript);
        }
    };

    recognition.onerror = (event) => {
        setVoiceStatus(`Error: ${event.error}`);
        stopListening();
    };

    recognition.onend = () => {
        stopListening();
    };
}

function toggleListening() {
    if (voiceListening) {
        stopListening();
        if (recognition) recognition.stop();
    } else {
        startListening();
    }
}

function startListening() {
    if (!recognition) {
        setVoiceStatus('Speech recognition not available');
        return;
    }
    voiceListening = true;
    document.getElementById('voice-mic-btn').classList.add('listening');
    document.getElementById('voice-status').textContent = 'Listening...';
    recognition.start();
}

function stopListening() {
    voiceListening = false;
    document.getElementById('voice-mic-btn').classList.remove('listening');
    document.getElementById('voice-status').textContent = '';
}

function setupTextFallback() {
    const input = document.getElementById('voice-text-input');
    const sendBtn = document.getElementById('voice-send-btn');

    if (sendBtn) {
        sendBtn.addEventListener('click', () => {
            const text = input.value.trim();
            if (text) processVoiceQuery(text);
        });
    }

    if (input) {
        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                const text = input.value.trim();
                if (text) processVoiceQuery(text);
            }
        });
    }
}

async function processVoiceQuery(text) {
    const responseEl = document.getElementById('voice-response');
    const statusEl = document.getElementById('voice-status');

    responseEl.innerHTML = '<div class="loading-spinner"></div>';
    statusEl.textContent = 'Processing...';

    try {
        const result = await api.voiceQuery(text);

        let html = `<div class="intent-badge">${result.intent} (${(result.confidence * 100).toFixed(0)}%)</div>`;
        html += `<p>${result.response}</p>`;
        html += `<div style="margin-top:12px;font-size:11px;color:var(--text-muted);">
            Source: ${result.source} | Time: ${result.processing_time_ms}ms</div>`;

        responseEl.innerHTML = html;
        statusEl.textContent = '';

        if ('speechSynthesis' in window) {
            speakResponse(result.response);
        }
    } catch (e) {
        responseEl.innerHTML = `<div class="error-state">Error: ${e.message}</div>`;
        statusEl.textContent = '';
    }
}

function speakResponse(text) {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;

    utterance.onstart = () => {
        document.getElementById('voice-speak-btn').disabled = true;
        document.getElementById('voice-stop-btn').disabled = false;
    };
    utterance.onend = () => {
        document.getElementById('voice-speak-btn').disabled = false;
        document.getElementById('voice-stop-btn').disabled = true;
    };

    window.speechSynthesis.speak(utterance);
}

function stopSpeaking() {
    window.speechSynthesis.cancel();
    document.getElementById('voice-speak-btn').disabled = false;
    document.getElementById('voice-stop-btn').disabled = true;
}

function setVoiceStatus(text) {
    document.getElementById('voice-status').textContent = text;
}
