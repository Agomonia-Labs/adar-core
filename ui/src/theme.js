import { createTheme } from '@mui/material/styles'
import tenant from './tenant'

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: {
      main:  tenant.primaryColor,
      light: tenant.primaryLight,
      dark:  tenant.primaryDark,
    },
    secondary: {
      main:  tenant.accentColor,
      light: tenant.accentLight,
      dark:  tenant.accentDark,
    },
    background: {
      default: tenant.bgDefault,
      paper:   tenant.bgPaper,
    },
    text: {
      primary:   tenant.textPrimary,
      secondary: tenant.textSecondary,
    },
    divider: tenant.divider,
  },
  typography: {
    fontFamily: tenant.fontFamily,
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
          border: `1px solid ${tenant.divider}`,
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
          backgroundColor: tenant.bgDefault,
          color: tenant.primaryDark,
          border: `1px solid ${tenant.divider}`,
        },
      },
    },
    MuiInputBase: {
      styleOverrides: {
        root: {
          backgroundColor: tenant.bgDefault,
        },
      },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        notchedOutline: {
          borderColor: tenant.divider,
        },
      },
    },
    MuiDivider: {
      styleOverrides: {
        root: {
          borderColor: tenant.divider,
        },
      },
    },
  },
})

export default theme
