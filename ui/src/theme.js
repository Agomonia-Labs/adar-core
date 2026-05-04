import { createTheme } from '@mui/material/styles'

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main: '#2EB87E',
      light: '#5DCAA5',
      dark: '#1A8A5A',
    },
    secondary: {
      main: '#EF9F27',     // cricket amber
      light: '#FAC775',
      dark: '#BA7517',
    },
    background: {
      default: '#F5FBF7',
      paper: '#FFFFFF',
    },
    text: {
      primary: '#1A3326',
      secondary: '#5A8A70',
    },
    divider: '#C8E8D8',
  },
  typography: {
    fontFamily: '"Inter", "Roboto", "Helvetica Neue", sans-serif',
    h6: { fontWeight: 500 },
  },
  shape: {
    borderRadius: 10,
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
          border: '1px solid #C8E8D8',
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          fontWeight: 500,
        },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: 6,
          backgroundColor: '#EBF7F1',
          color: '#2E7A54',
          border: '1px solid #C8E8D8',
        },
      },
    },
    MuiInputBase: {
      styleOverrides: {
        root: {
          backgroundColor: '#F5FBF7',
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        notchedOutline: {
          borderColor: '#C8E8D8',
        },
      },
    },
    MuiDivider: {
      styleOverrides: {
        root: {
          borderColor: '#C8E8D8',
        },
      },
    },
  },
})

export default theme