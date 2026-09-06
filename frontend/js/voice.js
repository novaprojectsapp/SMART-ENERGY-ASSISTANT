// Voice Assistant - controlled SpeechRecognition lifecycle.
//
// States: IDLE -> LISTENING -> PROCESSING -> (SPEAKING) -> IDLE, or ERROR.
// One SpeechRecognition instance is created ONCE and reused across page
// visits. A session token protects against stale callbacks from a previous
// session toggling the UI off while a new session is active.

const VoiceState = {
    IDLE: 'IDLE',
    LISTENING: 'LISTENING',
    PROCESSING: 'PROCESSING',
    SPEAKING: 'SPEAKING',
    ERROR: 'ERROR',
};

let voiceState = VoiceState.IDLE;
let recognition = null;
let recognizerSupported = true;
let recognitionSessionId = 0;
let shouldStop = false;
let requestInFlight = false;
let pendingAbortEnd = false;
let textListenersBound = false;

const VOICE_ERROR_MESSAGES = {
    'not-allowed': 'Microphone permission is required for voice input.',
    'service-not-allowed': 'Speech recognition service is not allowed in this browser.',
    'audio-capture': 'No microphone was detected or the microphone is unavailable.',
    'no-speech': 'No speech detected. Please try again.',
    network: 'Speech recognition encountered a network/service error.',
    aborted: '',
};

function initVoice() {
    ensureSpeechRecognition();
    setupTextFallback();

    if (!recognizerSupported) {
        setVoiceStatus('Voice recognition is not supported in this browser. Please use Google Chrome or Microsoft Edge.');
    }
    updateVoiceUI();
}

function ensureSpeechRecognition() {
    if (recognition) return;

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        recognizerSupported = false;
        return;
    }

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.lang = 'en-US';

    recognition.onstart = () => {
        // Genuinely listening only if we still expect a recognizer session.
        if (voiceState === VoiceState.LISTENING) {
            setVoiceStatus('Listening... speak now.');
        }
    };

    recognition.onresult = (event) => {
        let transcript = '';
        for (let i = 0; i < event.results.length; i++) {
            if (event.results[i].isFinal) {
                transcript += event.results[i][0].transcript;
            }
        }
        transcript = transcript.trim();

        if (!transcript) return;

        document.getElementById('voice-text-input').value = transcript;

        if (voiceState === VoiceState.LISTENING && !requestInFlight) {
            // Advance to PROCESSING so recognition.onend does not clobber state.
            voiceState = VoiceState.PROCESSING;
            requestInFlight = true;
            updateVoiceUI();
            processVoiceQuery(transcript).finally(() => {
                requestInFlight = false;
                if (voiceState === VoiceState.PROCESSING) {
                    voiceState = VoiceState.IDLE;
                    updateVoiceUI();
                }
            });
        }
    };

    recognition.onerror = (event) => {
        console.error('SpeechRecognition error:', event.error, event);

        if (event.error === 'aborted') {
            // User pressed Stop: no error message, stay IDLE.
            if (pendingAbortEnd) pendingAbortEnd = false;
            if (voiceState === VoiceState.LISTENING && shouldStop) {
                voiceState = VoiceState.IDLE;
                updateVoiceUI();
            }
            return;
        }

        const message = VOICE_ERROR_MESSAGES[event.error] || 'Speech recognition error. Please try again.';
        if (event.error === 'not-allowed' || event.error === 'network' || event.error === 'audio-capture' || event.error === 'service-not-allowed') {
            setVoiceState(VoiceState.ERROR, message);
        } else {
            setVoiceStatus(message);
            if (voiceState === VoiceState.LISTENING) {
                voiceState = VoiceState.IDLE;
                updateVoiceUI();
            }
        }
    };

    recognition.onend = () => {
        if (pendingAbortEnd) {
            pendingAbortEnd = false;
            return;
        }
        // A backend request is in flight - do not touch the UI.
        if (voiceState === VoiceState.PROCESSING) return;

        if (voiceState === VoiceState.LISTENING) {
            if (shouldStop) {
                voiceState = VoiceState.IDLE;
            } else {
                setVoiceStatus('No speech detected. Please try again.');
                voiceState = VoiceState.IDLE;
            }
            shouldStop = false;
            updateVoiceUI();
        }
    };
}

function toggleListening() {
    if (voiceState === VoiceState.LISTENING) {
        stopListening(true);
    } else if (voiceState === VoiceState.IDLE || voiceState === VoiceState.ERROR) {
        startListening();
    }
}

function startListening() {
    if (!recognizerSupported || !recognition) {
        setVoiceStatus('Voice recognition is not supported in this browser. Use text input.');
        return;
    }
    if (voiceState === VoiceState.LISTENING) return;

    if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
    }

    recognitionSessionId += 1;
    shouldStop = false;
    pendingAbortEnd = false;
    voiceState = VoiceState.LISTENING;
    updateVoiceUI();
    setVoiceStatus('Listening...');

    try {
        recognition.start();
    } catch (e) {
        // InvalidStateError: already started or starting. Reset cleanly instead
        // of leaving the UI stuck in LISTENING.
        console.error('recognition.start() failed:', e);
        voiceState = VoiceState.IDLE;
        updateVoiceUI();
        setVoiceStatus('Microphone is busy. Please try again.');
    }
}

function stopListening(userInitiated = true) {
    shouldStop = userInitiated;

    if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
    }

    if (recognition) {
        try {
            recognition.abort();
            pendingAbortEnd = true;
        } catch (e) {
            console.error('recognition.abort() failed:', e);
        }
        try {
            recognition.stop();
        } catch (e) {
            console.error('recognition.stop() failed:', e);
        }
    }

    voiceState = VoiceState.IDLE;
    updateVoiceUI();
    setVoiceStatus('');
}

function setVoiceState(state, message) {
    voiceState = state;
    if (voiceState === VoiceState.ERROR && message) {
        setVoiceStatus(message);
    }
    updateVoiceUI();
}

function getVoiceElements() {
    return {
        micBtn: document.getElementById('voice-mic-btn'),
        speakBtn: document.getElementById('voice-speak-btn'),
        stopBtn: document.getElementById('voice-stop-btn'),
        status: document.getElementById('voice-status'),
        response: document.getElementById('voice-response'),
        input: document.getElementById('voice-text-input'),
    };
}

function updateVoiceUI() {
    const { micBtn, speakBtn, stopBtn } = getVoiceElements();
    if (!micBtn) return;

    micBtn.classList.toggle('listening', voiceState === VoiceState.LISTENING);

    if (speakBtn) {
        speakBtn.disabled = voiceState !== VoiceState.IDLE;
    }
    if (stopBtn) {
        stopBtn.disabled = voiceState === VoiceState.IDLE;
    }
}

function setupTextFallback() {
    const input = document.getElementById('voice-text-input');
    const sendBtn = document.getElementById('voice-send-btn');
    if (!input || !sendBtn) return;

    // Bind once per page lifetime so navigation cannot stack duplicate
    // listeners that submit the same query multiple times.
    if (textListenersBound) return;
    textListenersBound = true;

    sendBtn.addEventListener('click', () => {
        const text = input.value.trim();
        if (text && !requestInFlight) submitTextQuery(text);
    });

    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            const text = input.value.trim();
            if (text && !requestInFlight) submitTextQuery(text);
        }
    });
}

function submitTextQuery(text) {
    if (requestInFlight) return;
    requestInFlight = true;
    voiceState = VoiceState.PROCESSING;
    updateVoiceUI();
    processVoiceQuery(text).finally(() => {
        requestInFlight = false;
        if (voiceState === VoiceState.PROCESSING) {
            voiceState = VoiceState.IDLE;
            updateVoiceUI();
        }
    });
}

async function processVoiceQuery(text) {
    const { response, status, speakBtn, stopBtn } = getVoiceElements();
    if (!response) return;

    response.innerHTML = '<div class="loading-spinner"></div>';
    if (status) status.textContent = 'Processing...';

    try {
        const result = await api.voiceQuery(text);

        let html = `<div class="intent-badge">${result.intent} (${(result.confidence * 100).toFixed(0)}%)</div>`;
        html += `<p>${result.response}</p>`;
        html += `<div style="margin-top:12px;font-size:11px;color:var(--text-muted);">
            Source: ${result.source} | Time: ${result.processing_time_ms}ms</div>`;

        response.innerHTML = html;
        if (status) status.textContent = '';

        if (speakBtn) speakBtn.disabled = false;
        if (stopBtn) stopBtn.disabled = true;

        if (voiceState === VoiceState.PROCESSING) {
            voiceState = VoiceState.IDLE;
            updateVoiceUI();
        }
    } catch (e) {
        console.error('Voice query failed:', e);
        response.innerHTML = `<div class="error-state">Error: ${e.message || 'Request failed'}</div>`;
        if (status) status.textContent = '';
        if (voiceState === VoiceState.PROCESSING) {
            voiceState = VoiceState.IDLE;
            updateVoiceUI();
        }
    }
}

function speakResponse(text) {
    if (!text || voiceState !== VoiceState.IDLE) return;
    if (!('speechSynthesis' in window)) return;

    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.0;
    utterance.pitch = 1.0;

    voiceState = VoiceState.SPEAKING;
    updateVoiceUI();

    utterance.onend = () => {
        if (voiceState === VoiceState.SPEAKING) {
            voiceState = VoiceState.IDLE;
            updateVoiceUI();
        }
    };
    utterance.onerror = () => {
        if (voiceState === VoiceState.SPEAKING) {
            voiceState = VoiceState.IDLE;
            updateVoiceUI();
        }
    };

    window.speechSynthesis.speak(utterance);
}

function stopSpeaking() {
    if (window.speechSynthesis) {
        window.speechSynthesis.cancel();
    }
    if (voiceState === VoiceState.LISTENING) {
        stopListening(true);
        return;
    }
    if (voiceState === VoiceState.SPEAKING) {
        voiceState = VoiceState.IDLE;
        updateVoiceUI();
    }
    const { stopBtn } = getVoiceElements();
    if (stopBtn) stopBtn.disabled = true;
}

function setVoiceStatus(text) {
    const { status } = getVoiceElements();
    if (status) status.textContent = text;
}

function destroyVoice() {
    stopListening(true);
}