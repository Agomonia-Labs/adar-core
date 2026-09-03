// hooks/useSpeech.js
// STT (speech-to-text) + TTS (text-to-speech) using tenant-selected language
// Used by ChatTab in App.jsx

import { useState, useRef, useCallback, useEffect } from 'react'

const API_URL = import.meta.env.VITE_API_URL || ''
const SILENT_AUDIO =
  'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA='
const STOP_COMMAND_RE = /\b(stop|pause|cancel|quiet|detener|para|silencio)\b|থামুন|থামো|বন্ধ করুন|বন্ধ করো|চুপ|স্টপ|পজ|বাতিল|रुको|बंद करो|चुप|رکو|بند کرو|خاموش|توقف|أوقف|صمت/i

function audioUrlFromBase64(base64Audio) {
  const raw = atob(base64Audio)
  const bytes = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
  return URL.createObjectURL(new Blob([bytes], { type:'audio/mpeg' }))
}

function arrayBufferFromBase64(base64Audio) {
  const raw = atob(base64Audio)
  const bytes = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
  return bytes.buffer
}

function toSpeechText(text) {
  return (text || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\|.+\|/g, ' ')
    .replace(/#{1,6}\s/g, '')
    .replace(/[*_#>`|~\-]+/g, ' ')
    .replace(/([।.!?])\s*/g, '$1 ')
    .replace(/\s+/g, ' ')
    .trim()
}

function splitSpeechText(text, maxLength = 360) {
  const parts = []
  const sentences = text.match(/[^।.!?]+[।.!?]?/g) || [text]

  for (const rawSentence of sentences) {
    const sentence = rawSentence.trim()
    if (!sentence) continue

    if (sentence.length <= maxLength) {
      parts.push(sentence)
      continue
    }

    let chunk = ''
    for (const word of sentence.split(/\s+/)) {
      if ((chunk + ' ' + word).trim().length > maxLength && chunk) {
        parts.push(chunk.trim())
        chunk = word
      } else {
        chunk = `${chunk} ${word}`.trim()
      }
    }
    if (chunk) parts.push(chunk.trim())
  }

  return parts.slice(0, 8)
}

/**
 * useSpeech
 *
 * Provides:
 *   listening      — bool, true while mic is active
 *   isSpeaking     — bool, true while TTS is playing
 *   supported      — bool, browser supports STT
 *   startListening — fn()
 *   stopListening  — fn()
 *   speakBangla    — fn(text: string) — speaks text in the selected voice.
 *                    Name kept for compatibility with existing App.jsx.
 *   stopSpeaking   — fn()
 *
 * Options:
 *   lang      — STT/TTS language (default 'en-US')
 *   onResult  — fn(transcript: string) called when speech recognised
 *   onError   — fn(errorMessage: string)
 */
export function useSpeech({ lang = 'en-US', labels = {}, onResult, onError } = {}) {
  const [listening,  setListening]  = useState(false)
  const [isSpeaking, setIsSpeaking] = useState(false)
  const recognitionRef = useRef(null)
  const mediaRecRef = useRef(null)
  const chunksRef = useRef([])
  const cloudStopTimerRef = useRef(null)
  const silenceTimerRef = useRef(null)
  const recorderAudioContextRef = useRef(null)
  const playbackAudioContextRef = useRef(null)
  const playbackSourceRef = useRef(null)
  const interruptRecognitionRef = useRef(null)
  const interruptActiveRef = useRef(false)
  const audioRef = useRef(null)
  const ttsUrlsRef = useRef([])
  const speakRunRef = useRef(0)
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
  const webSpeechSupported = Boolean(SpeechRecognition)
  const cloudSttSupported = Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder)
  const isSafari = /^((?!chrome|android).)*safari/i.test(navigator.userAgent)
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
  const preferCloudStt = cloudSttSupported && (isSafari || isIOS || !webSpeechSupported)
  const supported = webSpeechSupported || cloudSttSupported

  const stopSpeakingRef = useRef(null)

  const getAudio = useCallback(() => {
    if (!audioRef.current) {
      audioRef.current = new Audio()
      audioRef.current.preload = 'none'
    }
    return audioRef.current
  }, [])

  const unlockPlayback = useCallback(() => {
    const AudioCtx = window.AudioContext || window.webkitAudioContext
    if (AudioCtx && !playbackAudioContextRef.current) {
      playbackAudioContextRef.current = new AudioCtx()
    }
    const context = playbackAudioContextRef.current
    context?.resume?.().then(() => {
      const buffer = context.createBuffer(1, 1, context.sampleRate)
      const source = context.createBufferSource()
      source.buffer = buffer
      source.connect(context.destination)
      source.start(0)
    }).catch(() => {})

    const audio = getAudio()
    audio.pause()
    audio.src = SILENT_AUDIO
    audio.play().catch(() => {})
  }, [getAudio])

  // ── Initialise SpeechRecognition ──────────────────────────────────────────
  useEffect(() => {
    if (!webSpeechSupported) return

    const rec = new SpeechRecognition()
    rec.lang            = lang
    rec.interimResults  = false
    rec.maxAlternatives = 1
    rec.continuous      = false

    rec.onresult = (event) => {
      const transcript = event.results[0][0].transcript
      setListening(false)
      if (transcript.trim()) onResult?.(transcript.trim())
    }

    rec.onerror = (e) => {
      setListening(false)
      const msgs = {
        'no-speech':   labels.noSpeech || 'কথা শোনা যায়নি — আবার চেষ্টা করুন।',
        'not-allowed': labels.micPermission || 'মাইক্রোফোন অ্যাক্সেস দিন।',
        'network':     labels.network || 'নেটওয়ার্ক সমস্যা।',
      }
      onError?.(msgs[e.error] || `${labels.speechErrorPrefix || 'ভয়েস এরর'}: ${e.error}`)
    }

    rec.onend = () => setListening(false)

    recognitionRef.current = rec
  }, [SpeechRecognition, labels, lang, onResult, onError, webSpeechSupported])

  useEffect(() => {
    if (!webSpeechSupported) return

    const rec = new SpeechRecognition()
    rec.lang = lang
    rec.interimResults = true
    rec.maxAlternatives = 1
    rec.continuous = true

    rec.onresult = (event) => {
      let transcript = ''
      for (let i = event.resultIndex; i < event.results.length; i++) {
        transcript += event.results[i][0].transcript + ' '
      }
      if (STOP_COMMAND_RE.test(transcript)) {
        interruptActiveRef.current = false
        try {
          rec.abort()
        } catch {
          // Recognition may have already stopped.
        }
        stopSpeakingRef.current?.()
      }
    }

    rec.onerror = (e) => {
      // 'no-speech' and 'aborted' are routine in continuous mode (fires on
      // every silence gap / on our own deliberate rec.abort()) -- only log
      // anything unexpected.
      if (e.error !== 'no-speech' && e.error !== 'aborted') {
        console.warn('Interrupt listening error:', e.error)
      }
    }
    rec.onend = () => {
      if (!interruptActiveRef.current) return
      try {
        rec.start()
      } catch (err) {
        console.warn('Interrupt listening failed to restart:', err)
        interruptActiveRef.current = false
      }
    }

    interruptRecognitionRef.current = rec
    return () => {
      interruptActiveRef.current = false
      rec.abort()
    }
  }, [SpeechRecognition, lang, webSpeechSupported])

  const startInterruptListening = useCallback(() => {
    const rec = interruptRecognitionRef.current
    if (!rec || listening) return
    interruptActiveRef.current = true
    try {
      rec.start()
    } catch (err) {
      // The speech engine sometimes isn't ready for a second (interrupt)
      // SpeechRecognition instance the instant the first one (regular STT)
      // just stopped -- "recognition has already started" / InvalidStateError.
      // One short retry covers that race; log so a real, non-transient
      // failure (e.g. this browser truly disallows concurrent recognition)
      // is at least visible in devtools instead of silently never working.
      console.warn('Interrupt listening failed to start, retrying:', err)
      setTimeout(() => {
        if (!interruptActiveRef.current) return
        try {
          rec.start()
        } catch (retryErr) {
          console.warn('Interrupt listening retry also failed — spoken "stop" will not interrupt playback in this browser/session:', retryErr)
          interruptActiveRef.current = false
        }
      }, 300)
    }
  }, [listening])

  const stopInterruptListening = useCallback(() => {
    interruptActiveRef.current = false
    try {
      interruptRecognitionRef.current?.abort()
    } catch {
      // Recognition may already be stopped.
    }
  }, [])

  const startCloudSTT = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio:true })
      let heardSpeech = false
      const stopRecorder = () => {
        if (mediaRecRef.current?.state === 'recording') mediaRecRef.current.stop()
      }
      const clearRecorderTimers = () => {
        if (cloudStopTimerRef.current) clearTimeout(cloudStopTimerRef.current)
        if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
        cloudStopTimerRef.current = null
        silenceTimerRef.current = null
      }
      const closeAudioContext = () => {
        recorderAudioContextRef.current?.close?.().catch(() => {})
        recorderAudioContextRef.current = null
      }
      let monitorSilence = null
      const mimeType = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/ogg;codecs=opus',
        'audio/ogg',
        'audio/mp4',
      ].find(m => MediaRecorder.isTypeSupported?.(m)) || ''

      const mr = new MediaRecorder(stream, mimeType ? { mimeType } : {})
      chunksRef.current = []

      try {
        const AudioCtx = window.AudioContext || window.webkitAudioContext
        if (AudioCtx) {
          const audioContext = new AudioCtx()
          recorderAudioContextRef.current = audioContext
          const analyser = audioContext.createAnalyser()
          const source = audioContext.createMediaStreamSource(stream)
          analyser.fftSize = 1024
          const data = new Uint8Array(analyser.fftSize)
          source.connect(analyser)

          monitorSilence = () => {
            if (mr.state !== 'recording') return
            analyser.getByteTimeDomainData(data)
            let sum = 0
            for (let i = 0; i < data.length; i++) {
              const centered = data[i] - 128
              sum += centered * centered
            }
            const volume = Math.sqrt(sum / data.length)

            if (volume > 8) {
              heardSpeech = true
              if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
              silenceTimerRef.current = null
            } else if (heardSpeech && !silenceTimerRef.current) {
              silenceTimerRef.current = setTimeout(stopRecorder, 1200)
            }

            requestAnimationFrame(monitorSilence)
          }
        }
      } catch (err) {
        console.warn('Silence detection unavailable:', err)
      }

      mr.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }
      mr.onstop = async () => {
        clearRecorderTimers()
        closeAudioContext()
        stream.getTracks().forEach(t => t.stop())
        setListening(false)
        const actualMime = mimeType || 'audio/webm'
        const blob = new Blob(chunksRef.current, { type:actualMime })
        const reader = new FileReader()
        reader.onloadend = async () => {
          try {
            const token = localStorage.getItem('adar_token') || ''
            const resp = await fetch(`${API_URL}/api/stt`, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`,
              },
              body: JSON.stringify({
                audio: reader.result.split(',')[1],
                lang,
                mime: actualMime,
              }),
            })
            if (!resp.ok) throw new Error(`STT HTTP ${resp.status}`)
            const data = await resp.json()
            if (data.text?.trim()) onResult?.(data.text.trim())
            else onError?.(labels.notUnderstood || 'কথা বোঝা যায়নি, আবার চেষ্টা করুন।')
          } catch (err) {
            onError?.(`${labels.voiceServerProblemPrefix || 'ভয়েস সার্ভার সমস্যা'}: ${err.message}`)
          }
        }
        reader.readAsDataURL(blob)
      }

      mediaRecRef.current = mr
      mr.start()
      setListening(true)
      monitorSilence?.()
      cloudStopTimerRef.current = setTimeout(stopRecorder, 10000)
    } catch (err) {
      setListening(false)
      onError?.(`${labels.micStartProblemPrefix || 'মাইক্রোফোন চালু করা যায়নি'}: ${err.message}`)
    }
  }, [labels, lang, onError, onResult])

  // ── STT controls ──────────────────────────────────────────────────────────
  const startListening = useCallback(() => {
    if (listening) return
    // Stop any active speech before listening
    unlockPlayback()
    setIsSpeaking(false)
    if (preferCloudStt) {
      startCloudSTT()
      return
    }
    if (webSpeechSupported && recognitionRef.current) {
      recognitionRef.current.start()
      setListening(true)
      return
    }
    if (cloudSttSupported) startCloudSTT()
  }, [cloudSttSupported, getAudio, listening, preferCloudStt, startCloudSTT, webSpeechSupported])

  const stopListening = useCallback(() => {
    if (mediaRecRef.current?.state === 'recording') mediaRecRef.current.stop()
    else recognitionRef.current?.stop()
    setListening(false)
  }, [])

  // ── TTS: speak reply using the tenant language selected in tenant.js ──────
  const speakBangla = useCallback(async (text) => {
    const chunks = splitSpeechText(toSpeechText(text))
    if (!chunks.length) return false

    const runId = speakRunRef.current + 1
    speakRunRef.current = runId
    setIsSpeaking(true)
    startInterruptListening()

    try {
      const audio = getAudio()
      audio.pause()
      audio.onended = null
      audio.onerror = null
      await playbackAudioContextRef.current?.resume?.().catch(() => {})

      const playChunk = async (index) => {
        if (speakRunRef.current !== runId) return false
        if (index >= chunks.length) {
          stopInterruptListening()
          setIsSpeaking(false)
          return true
        }

        const resp = await fetch(`${API_URL}/api/demo/tts`, {
          method: 'POST',
          headers: { 'Content-Type':'application/json' },
          body: JSON.stringify({ text:chunks[index], lang }),
        })
        if (!resp.ok) throw new Error(`TTS HTTP ${resp.status}`)
        const data = await resp.json()
        if (speakRunRef.current !== runId) return false
        if (!data.audio) return false

        const context = playbackAudioContextRef.current
        if (context) {
          const decoded = await context.decodeAudioData(arrayBufferFromBase64(data.audio).slice(0))
          if (speakRunRef.current !== runId) return false
          return new Promise((resolve) => {
            const source = context.createBufferSource()
            playbackSourceRef.current = source
            source.buffer = decoded
            source.connect(context.destination)
            source.onended = async () => {
              if (playbackSourceRef.current === source) playbackSourceRef.current = null
              resolve(await playChunk(index + 1))
            }
            source.start(0)
          })
        }

        const url = audioUrlFromBase64(data.audio)
        ttsUrlsRef.current.push(url)
        return new Promise((resolve, reject) => {
          audio.src = url
          audio.onended = async () => {
            URL.revokeObjectURL(url)
            try {
              resolve(await playChunk(index + 1))
            } catch (err) {
              reject(err)
            }
          }
          audio.onerror = () => {
            URL.revokeObjectURL(url)
            reject(new Error('Audio playback failed'))
          }
          audio.play().catch(reject)
        })
      }

      return await playChunk(0)
    } catch (err) {
      console.warn('TTS playback error:', err)
      if (speakRunRef.current === runId) setIsSpeaking(false)
      stopInterruptListening()
      return false
    }
  }, [getAudio, lang, startInterruptListening, stopInterruptListening])

  const stopSpeaking = useCallback(() => {
    speakRunRef.current += 1
    stopInterruptListening()
    try {
      playbackSourceRef.current?.stop?.()
    } catch {
      // Source may have already ended.
    }
    playbackSourceRef.current = null
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.onended = null
      audioRef.current.onerror = null
    }
    setIsSpeaking(false)
  }, [stopInterruptListening])

  useEffect(() => {
    stopSpeakingRef.current = stopSpeaking
  }, [stopSpeaking])

  useEffect(() => () => {
    recognitionRef.current?.abort()
    if (mediaRecRef.current?.state === 'recording') mediaRecRef.current.stop()
    if (cloudStopTimerRef.current) clearTimeout(cloudStopTimerRef.current)
    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current)
    recorderAudioContextRef.current?.close?.().catch(() => {})
    try {
      playbackSourceRef.current?.stop?.()
    } catch {
      // Source may have already ended.
    }
    playbackAudioContextRef.current?.close?.().catch(() => {})
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.onended = null
      audioRef.current.onerror = null
    }
    ttsUrlsRef.current.forEach(url => URL.revokeObjectURL(url))
    ttsUrlsRef.current = []
  }, [])

  return { listening, isSpeaking, supported, startListening, stopListening, speakBangla, stopSpeaking }
}
