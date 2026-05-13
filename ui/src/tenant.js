/**
 * ui/src/tenant.js
 * ─────────────────
 * Single source of truth for all domain-specific strings, colors, and flags.
 * Reads VITE_DOMAIN env var at build time. Falls back to detecting from
 * VITE_API_URL so you don't need a second env var if the URL already differs.
 *
 * .env.arcl:       VITE_DOMAIN=arcl
 * .env.geetabitan: VITE_DOMAIN=geetabitan
 */

const _domain =
  import.meta.env.VITE_DOMAIN ||
  (import.meta.env.VITE_API_URL?.includes('geetabitan') ? 'geetabitan' : 'arcl')

const TENANTS = {

  arcl: {
    id:            'arcl',
    appTitle:      'Adar ARCL',
    name:          'American Recreational Cricket League',
    shortName:     'ARCL',
    subtitle:      'Cricket Assistant',
    logoText:      'আদর',

    // Colors — passed into createAppTheme()
    primaryColor:  '#2EB87E',
    primaryLight:  '#5DCAA5',
    primaryDark:   '#1A8A5A',
    accentColor:   '#EF9F27',
    accentLight:   '#FAC775',
    accentDark:    '#BA7517',
    bgDefault:     '#F5FBF7',
    bgPaper:       '#FFFFFF',
    textPrimary:   '#1A3326',
    textSecondary: '#5A8A70',
    divider:       '#C8E8D8',

    // Font — Inter works fine for English
    fontFamily: '"Inter", "Roboto", "Helvetica Neue", sans-serif',

    // Chat strings
    welcomeMessage:
      "Hi! I'm Adar, the ARCL cricket assistant. I can help you with " +
      "league rules, player statistics, team history, and schedules.\n\nWhat would you like to know?",
    placeholder:    'Ask about rules, players, teams, or standings…',
    typingText:     'Searching ARCL data…',
    clearMessage:   'Session cleared. How can I help you with ARCL cricket?',
    footerText:     'Powered by Adar · Data from arcl.org',

    // Suggested questions shown on first load
    suggestedQuestions: [
      'What is the wide rule in ARCL?',
      'Can a player play for two teams in the same season?',
      'Show my team players in Spring 2026',
      'Show my team schedule in Spring 2026',
      'How does the points table work?',
      'Who scored the most runs in Div H?',
    ],

    // Register page
    registerSubtitle:    'ARCL teams · 14-day free trial · No credit card until trial ends',
    showTeamDropdown:    true,      // fetches /api/arcl/teams for autocomplete
    teamDropdownLabel:   'Your ARCL team',
    teamDropdownHelper:  'Select your team or type if not found',

    // Login page
    loginTitle:   'Adar ARCL',
    loginCaption: 'Powered by Adar · American Recreational Cricket League',
  },

  geetabitan: {
    id:            'geetabitan',
    appTitle:      'আদর · গীতবিতান',
    name:          'গীতবিতান — রবীন্দ্রনাথ ঠাকুরের গান',
    shortName:     'Geetabitan',
    subtitle:      'রবীন্দ্রসঙ্গীত সহায়ক',
    logoText:      'আদর',

    // Colors — deep red and gold for Tagore / Rabindra Sangeet
    primaryColor:  '#8B1A1A',
    primaryLight:  '#B24444',
    primaryDark:   '#5C0F0F',
    accentColor:   '#D4A017',
    accentLight:   '#E8C55A',
    accentDark:    '#A07810',
    bgDefault:     '#FDF6F0',
    bgPaper:       '#FFFFFF',
    textPrimary:   '#2C1A0E',
    textSecondary: '#7A5C3A',
    divider:       '#E8D5C0',

    // Font — Hind Siliguri for Bengali readability
    // The <link> for this font is added in index.html
    fontFamily: '"Hind Siliguri", "Noto Sans Bengali", "Roboto", sans-serif',

    // Chat strings
    welcomeMessage:
      'নমস্কার! আমি আদর — গীতবিতানের সহায়ক। রবীন্দ্রনাথ ঠাকুরের যেকোনো গান, ' +
      'রাগ, তাল, পর্যায়, বা গানের অর্থ সম্পর্কে প্রশ্ন করুন।\n\nকী জানতে চান?',
    placeholder:    'বাংলায় গান খুঁজুন…',
    typingText:     'গীতবিতান খোঁজা হচ্ছে…',
    clearMessage:   'Session cleared. রবীন্দ্রসঙ্গীত বিষয়ে কিছু জানতে চাইলে বলুন।',
    footerText:     'Powered by Adar · গীতবিতান',

    // Suggested questions — full scope across all categories, rotated randomly in UI
    suggestedQuestions: [
      // গান খোঁজা
      'আমার সোনার বাংলা গানটি খুঁজুন',
      'একলা চলো রে গানটি দেখাও',
      'আনন্দলোকে মঙ্গলালোকে গানটি দেখাও',
      'যদি তোর ডাক শুনে কেউ না আসে',
      'আমার পরান যাহা চায় গানটি দেখাও',
      // রাগ অনুযায়ী
      'ভৈরবী রাগের গান দেখাও',
      'বাউল রাগের গান কী কী?',
      'কাফি রাগে রবীন্দ্রনাথের গান দেখাও',
      'ইমন রাগের গানগুলো দেখাও',
      // তাল অনুযায়ী
      'দাদরা তালের গান কী কী?',
      'কাহারবা তালে কতটি গান আছে?',
      'তিনতালের গান দেখাও',
      // পর্যায় অনুযায়ী
      'স্বদেশ পর্যায়ের গানগুলো দেখাও',
      'পূজা পর্যায়ে কতটি গান আছে?',
      'প্রেম পর্যায়ের গান দেখাও',
      'প্রকৃতি পর্যায়ের গান কী কী?',
      // অর্থ ও ব্যাখ্যা
      'একলা চলো রে গানের অর্থ কী?',
      'আমার সোনার বাংলা গানের প্রেক্ষাপট বলো',
      'আমার মাথা নত করে দাও গানের বার্তা কী?',
      'আনন্দধারা বহিছে ভুবনে গানের আবেগ কী?',
      // বিশেষ অনুসন্ধান
      'বর্ষার গান দেখাও',
      'বসন্তের গান কী কী আছে?',
      'দেশপ্রেমের গান দেখাও',
      'বিরহের গান দেখাও',
      'ভোরের গান কী কী?',
    ],

    // Register page
    registerSubtitle:    '14-day free trial · No credit card until trial ends',
    showTeamDropdown:    false,     // no team list for Geetabitan
    teamDropdownLabel:   '',
    teamDropdownHelper:  '',

    // Login page
    loginTitle:   'আদর · গীতবিতান',
    loginCaption: 'Powered by Adar · গীতবিতান',
  },
}

const tenant = TENANTS[_domain] || TENANTS.arcl
export default tenant