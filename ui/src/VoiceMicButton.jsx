// VoiceMicButton.jsx
// Mic button component — drop into your ADAR chat UI
// Renders: a mic FAB that records Bangla speech and plays back Bangla answer

import { useEffect } from 'react';
import { IconButton, Tooltip, CircularProgress, Box } from '@mui/material';
import MicIcon from '@mui/icons-material/Mic';
import MicOffIcon from '@mui/icons-material/MicOff';
import VolumeUpIcon from '@mui/icons-material/VolumeUp';
import StopIcon from '@mui/icons-material/Stop';
import { useVoiceChat } from './useVoiceChat';

/**
 * VoiceMicButton
 *
 * Props:
 *   onSendMessage  — async fn(text: string) → string
 *                    Same function your chat form already calls.
 *                    Must return the AI reply string.
 *   disabled       — disable the button (e.g. while a text message is pending)
 *   sx             — MUI sx overrides
 */
export default function VoiceMicButton({ onSendMessage, disabled = false, sx = {} }) {
  const {
    isListening,
    isSpeaking,
    error,
    startListening,
    stopListening,
    stopSpeaking,
  } = useVoiceChat(onSendMessage, {
    lang: 'bn-BD',    // Bangla (Bangladesh) — change to 'bn-IN' for India
    ttsRate: 0.88,    // Slightly slower for clarity
    ttsPitch: 1.0,
    autoSpeak: true,
  });

  // Show error as a transient console warning (you can swap for a Snackbar)
  useEffect(() => {
    if (error) console.warn('[VoiceMicButton]', error);
  }, [error]);

  // ── Determine button state ──────────────────────────────────────────────────
  let icon, label, color, onClick, pulse;

  if (isSpeaking) {
    icon    = <StopIcon />;
    label   = 'উত্তর বন্ধ করুন';
    color   = 'warning';
    onClick = stopSpeaking;
    pulse   = false;
  } else if (isListening) {
    icon    = <MicOffIcon />;
    label   = 'শোনা বন্ধ করুন';
    color   = 'error';
    onClick = stopListening;
    pulse   = true;
  } else {
    icon    = <MicIcon />;
    label   = 'ভয়েসে প্রশ্ন করুন';
    color   = 'primary';
    onClick = startListening;
    pulse   = false;
  }

  return (
    <Tooltip title={label} placement="top">
      <Box
        component="span"
        sx={{
          position: 'relative',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          ...sx,
        }}
      >
        {/* Pulsing ring while listening */}
        {pulse && (
          <CircularProgress
            size={48}
            thickness={2}
            sx={{
              position: 'absolute',
              color: 'error.main',
              animation: 'voice-pulse 1.2s ease-in-out infinite',
              '@keyframes voice-pulse': {
                '0%':   { opacity: 1,   transform: 'scale(1)' },
                '50%':  { opacity: 0.4, transform: 'scale(1.25)' },
                '100%': { opacity: 1,   transform: 'scale(1)' },
              },
            }}
          />
        )}

        {/* Speaker wave while speaking */}
        {isSpeaking && (
          <VolumeUpIcon
            sx={{
              position: 'absolute',
              top: -14,
              right: -14,
              fontSize: 16,
              color: 'warning.main',
              animation: 'bounce 0.6s ease-in-out infinite alternate',
              '@keyframes bounce': {
                from: { transform: 'scale(1)' },
                to:   { transform: 'scale(1.4)' },
              },
            }}
          />
        )}

        <IconButton
          color={color}
          onClick={onClick}
          disabled={disabled && !isListening && !isSpeaking}
          size="large"
          sx={{
            bgcolor: pulse
              ? 'error.light'
              : isSpeaking
                ? 'warning.light'
                : 'primary.light',
            '&:hover': {
              bgcolor: pulse
                ? 'error.main'
                : isSpeaking
                  ? 'warning.main'
                  : 'primary.main',
              color: 'white',
            },
            transition: 'all 0.2s ease',
          }}
          aria-label={label}
        >
          {icon}
        </IconButton>
      </Box>
    </Tooltip>
  );
}
