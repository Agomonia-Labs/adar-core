/**
 * ui/src/tenant.js
 * ─────────────────
 * Single source of truth for all domain-specific strings, colors, and flags.
 * Reads VITE_DOMAIN env var at build time. Falls back to detecting from
 * VITE_API_URL so you don't need a second env var if the URL already differs.
 *
 * .env.arcl:       VITE_DOMAIN=arcl
 * .env.geetabitan: VITE_DOMAIN=geetabitan
 * .env.restaurants: VITE_DOMAIN=restaurants
 * .env.scheduling: VITE_DOMAIN=scheduling
 */

const _domain =
  import.meta.env.VITE_DOMAIN ||
  (import.meta.env.VITE_API_URL?.includes('geetabitan') ? 'geetabitan'
    : import.meta.env.VITE_API_URL?.includes('restaurant') ? 'restaurants'
    : 'arcl')

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
    evalLabels: {
      accuracy: 'Accuracy',
      completeness: 'Completeness',
      relevance: 'Relevance',
      format: 'Format',
      overall: 'Overall',
      scale: '5',
    },
    voice: {
      lang: 'en-IN',
      startTooltip: 'Speak',
      stopTooltip: 'Stop voice conversation',
      noSpeech: 'No speech heard. Please try again.',
      micPermission: 'Please allow microphone access.',
      network: 'Network problem.',
      speechErrorPrefix: 'Voice error',
      notUnderstood: 'Could not understand speech. Please try again.',
      voiceServerProblemPrefix: 'Voice server problem',
      micStartProblemPrefix: 'Could not start microphone',
    },

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
    registerSubtitle:    'ARCL teams · 30-day free trial · No credit card until trial ends',
    showTeamDropdown:    true,      // fetches /api/arcl/teams for autocomplete
    teamDropdownLabel:   'Your ARCL team',
    teamDropdownHelper:  'Select your team or type if not found',

    // Login page
    loginTitle:   'Adar ARCL',
    loginCaption: 'Powered by Adar · American Recreational Cricket League',
  },

  geetabitan: {
    // Tenant id/env var stays "geetabitan" (VITE_DOMAIN=geetabitan) so no
    // deployment config needs to change — only the DISPLAYED branding below
    // is "আদর সুর সংকলন" now that the web assistant covers Rabindra
    // Sangeet, Nazrul Geeti, Rajanikanta Sangeet, Atulprasad Sangeet, and
    // Dwijendra Sangeet.
    // iOS is a separate native/RN app with its own branding (see
    // adar-mobile/apps/geetabitan) and is kept in sync by hand — update
    // both when either changes.
    id:            'geetabitan',
    appTitle:      'আদর · সুর সংকলন',
    name:          'আদর সুর সংকলন — রবীন্দ্রসঙ্গীত, নজরুলগীতি, রজনীকান্তের গান, অতুলপ্রসাদের গান ও দ্বিজেন্দ্রগীতি',
    shortName:     'Sur Sankalan',
    subtitle:      'রবীন্দ্রসঙ্গীত, নজরুলগীতি, রজনীকান্তের গান, অতুলপ্রসাদের গান ও দ্বিজেন্দ্রগীতি সহায়ক',
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
      'স্বাগতম! আমি আদর — সুর সংকলনের সহায়ক। রবীন্দ্রনাথ ঠাকুর, কাজী নজরুল ইসলাম, ' +
      'রজনীকান্ত সেন, অতুলপ্রসাদ সেন বা দ্বিজেন্দ্রলাল রায়ের যেকোনো গান, রাগ, তাল, পর্যায়/সংকলন, বা গানের অর্থ সম্পর্কে প্রশ্ন করুন।\n\nকী জানতে চান?',
    placeholder:    'বাংলায় গান খুঁজুন…',
    typingText:     'গান খোঁজা হচ্ছে…',
    clearMessage:   'Session cleared. রবীন্দ্রসঙ্গীত, নজরুলগীতি, রজনীকান্তের গান, অতুলপ্রসাদের গান বা দ্বিজেন্দ্রগীতি বিষয়ে কিছু জানতে চাইলে বলুন।',
    footerText:     'Powered by Adar · সুর সংকলন',
    evalLabels: {
      accuracy: 'যথার্থতা',
      completeness: 'সম্পূর্ণতা',
      relevance: 'প্রাসঙ্গিক',
      format: 'বিন্যাস',
      overall: 'সামগ্রিক',
      scale: '৫',
    },
    voice: {
      lang: 'bn-IN',
      startTooltip: 'বাংলায় বলুন',
      stopTooltip: 'ভয়েস কথোপকথন বন্ধ করুন',
      noSpeech: 'কথা শোনা যায়নি — আবার চেষ্টা করুন।',
      micPermission: 'মাইক্রোফোন অ্যাক্সেস দিন।',
      network: 'নেটওয়ার্ক সমস্যা।',
      speechErrorPrefix: 'ভয়েস এরর',
      notUnderstood: 'কথা বোঝা যায়নি, আবার চেষ্টা করুন।',
      voiceServerProblemPrefix: 'ভয়েস সার্ভার সমস্যা',
      micStartProblemPrefix: 'মাইক্রোফোন চালু করা যায়নি',
    },

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

    // Nazrul Geeti suggested questions — additive, separate pool from
    // suggestedQuestions above (which stays the Rabindra Sangeet set so
    // today's random-6 behavior is unchanged). Surfaced via a composer
    // toggle in the chat UI — wiring that toggle into App.jsx (reading this
    // array and passing the selected composer through to the chat request)
    // is the next incremental step, not yet done in this pass.
    suggestedQuestionsNazrul: [
      // গান খোঁজা
      'বাগিচায় বুলবুলি তুই গানটি খুঁজুন',
      'কারার ঐ লৌহকপাট গানটি দেখাও',
      'মোরা ঝঞ্জার মতো উদ্দাম গানটি দেখাও',
      'দূর দ্বীপবাসিনী গানটি দেখাও',
      // সংকলন অনুযায়ী
      'বুলবুল সংকলনের গানগুলো দেখাও',
      'সন্ধ্যা সংকলনে কতটি গান আছে?',
      'জুলফিকার সংকলনের গান দেখাও',
      'বনগীতি সংকলনের গান কী কী?',
      // রাগ ও তাল অনুযায়ী
      'ভৈরবী রাগে নজরুলগীতি দেখাও',
      'দাদরা তালে নজরুলগীতি কী কী আছে?',
      // অর্থ ও ব্যাখ্যা
      'কারার ঐ লৌহকপাট গানের অর্থ কী?',
      'বাগিচায় বুলবুলি তুই গানের প্রেক্ষাপট বলো',
      // বিশেষ অনুসন্ধান
      'দেশপ্রেমের নজরুলগীতি দেখাও',
      'বিদ্রোহের গান দেখাও',
    ],

    // Rajanikanta Sen suggested questions — additive, same pattern as
    // suggestedQuestionsNazrul above: a separate pool, surfaced only
    // through the same composer toggle once that's wired into App.jsx.
    suggestedQuestionsRajanikanta: [
      // গান খোঁজা
      'সূচনা গানটি খুঁজুন',
      'আশা গানটি দেখাও',
      'বঙ্গমাতা গানটি দেখাও',
      'মহাষ্টমীর ঊষা গানটি দেখাও',
      // সংকলন অনুযায়ী
      'বাণী সংকলনের গানগুলো দেখাও',
      'আনন্দময়ী সংকলনে কতটি গান আছে?',
      'কল্যাণী সংকলনের গান দেখাও',
      'শেষ দান সংকলনের গান কী কী?',
      // রাগ ও তাল অনুযায়ী
      'গৌরী রাগে রজনীকান্তের গান দেখাও',
      'একতালা তালে রজনীকান্তের গান কী কী আছে?',
      // অর্থ ও ব্যাখ্যা
      'আশা গানের অর্থ কী?',
      'বঙ্গমাতা গানের প্রেক্ষাপট বলো',
      // বিশেষ অনুসন্ধান
      'ভক্তিমূলক রজনীকান্তের গান দেখাও',
      'দেশপ্রেমের রজনীকান্তের গান দেখাও',
    ],

    // Atulprasad Sen suggested questions — additive, same pattern as
    // suggestedQuestionsNazrul/suggestedQuestionsRajanikanta above: a
    // separate pool, surfaced only through the same composer toggle once
    // that's wired into App.jsx. No "সংকলন/পর্যায় অনুযায়ী" section here —
    // unlike Nazrul/Rajanikanta, Atulprasad's onushilon.org corpus confirms
    // a paryay/book grouping on only 4 of his 205 songs (see
    // atulprasad_lyrics_loader.py's docstring), too sparse to suggest as a
    // real filter. Every title/raag/taal below is a verified value from
    // that corpus, not a guess.
    suggestedQuestionsAtulprasad: [
      // গান খোঁজা
      'মোদের গরব, মোদের আশা গানটি খুঁজুন',
      'উঠ গো ভারত-লক্ষ্মী, উঠ গানটি দেখাও',
      'বলো বলো বলো সবে, শত-বীণা-বেণু-রবে গানটি দেখাও',
      // রাগ ও তাল অনুযায়ী
      'খাম্বাজ রাগে অতুলপ্রসাদের গান দেখাও',
      'একতাল তালে অতুলপ্রসাদের গান কী কী আছে?',
      // অর্থ ও ব্যাখ্যা
      'মোদের গরব, মোদের আশা গানের অর্থ কী?',
      // বিশেষ অনুসন্ধান
      'অতুলপ্রসাদের গান থেকে কিছু গান দেখাও',
    ],

    // Dwijendralal Roy (দ্বিজেন্দ্রগীতি) suggested questions — additive,
    // same pattern as suggestedQuestionsNazrul/Rajanikanta above: a
    // separate pool, surfaced only through the same composer toggle once
    // that's wired into App.jsx. Uses "নাটক অনুযায়ী" (by play) rather than
    // "সংকলন/পর্যায় অনুযায়ী" — Dwijendralal's songs are organized by the
    // historical play they were written for (সাজাহান/চন্দ্রগুপ্ত/মেবার
    // পতন/রাণা প্রতাপ সিংহ), per CATEGORY_ORGANIZED_COMPOSERS. Raag/taal is
    // sparse (4 of 18 songs, straight from the 1965 anthology source text)
    // — only those confirmed values are used below, never guessed.
    suggestedQuestionsDwijendralal: [
      // গান খোঁজা
      'ধনধান্য পুষ্পভরা গানটি খুঁজুন',
      'মেবার পাহাড় গানটি দেখাও',
      'আমার কুটীররাণী সে যে গো গানটি দেখাও',
      // নাটক অনুযায়ী
      'সাজাহান নাটকের গান দেখাও',
      'চন্দ্রগুপ্ত নাটকের গান দেখাও',
      'মেবার পতন নাটকের গান কী কী আছে?',
      'রাণা প্রতাপ সিংহ নাটকের গান দেখাও',
      // রাগ ও তাল অনুযায়ী
      'হাম্বির রাগে দ্বিজেন্দ্রগীতি দেখাও',
      'ভীমপলশ্রী রাগে দ্বিজেন্দ্রগীতি কী কী আছে?',
      // অর্থ ও প্রেক্ষাপট
      'ধনধান্য পুষ্পভরা গানের প্রেক্ষাপট বলো',
      'মেবার পাহাড় গানের অর্থ কী?',
      // বিশেষ অনুসন্ধান
      'দেশাত্মবোধক দ্বিজেন্দ্রগীতি দেখাও',
      'ধনধান্য পুষ্পভরা দ্বিজেন্দ্রলালের গানটি খুঁজুন',
    ],

    // Register page
    registerSubtitle:    '14-day free trial · No credit card until trial ends',
    showTeamDropdown:    false,     // no team list for Sur Sankalan
    teamDropdownLabel:   '',
    teamDropdownHelper:  '',

    // Login page
    loginTitle:   'আদর · সুর সংকলন',
    loginCaption: 'Powered by Adar · সুর সংকলন',
  },

  restaurants: {
    id:            'restaurants',
    appTitle:      'Adar Restaurants',
    name:          'Restaurant Food Recommender',
    shortName:     'Restaurants',
    subtitle:      'Food, Menu, Price & Review Assistant',
    logoText:      'Adar',

    primaryColor:  '#0F766E',
    primaryLight:  '#5EBFB7',
    primaryDark:   '#0B4F4A',
    accentColor:   '#D97706',
    accentLight:   '#F5B04D',
    accentDark:    '#92400E',
    bgDefault:     '#F7FAF8',
    bgPaper:       '#FFFFFF',
    textPrimary:   '#17211F',
    textSecondary: '#61736F',
    divider:       '#CFE3DE',

    fontFamily: '"Inter", "Roboto", "Helvetica Neue", sans-serif',

    welcomeMessage:
      "Hi! I'm Adar, your restaurant food recommender. Ask for restaurants or menu items by location, cuisine, budget, quantity, reviews, or price comparison.\n\nTry: “Find Thai dinner near Seattle under $25.”",
    placeholder:    'Ask for Thai, Indian, Italian, American, price comparisons…',
    typingText:     'Searching restaurants, menus, prices, and reviews…',
    clearMessage:   'Session cleared. What food should we compare next?',
    footerText:     'Powered by Adar · Restaurant menu data includes source freshness and confidence',
    evalLabels: {
      accuracy: 'Accuracy',
      completeness: 'Completeness',
      relevance: 'Relevance',
      format: 'Format',
      overall: 'Overall',
      scale: '5',
    },
    voice: {
      lang: 'en-US',
      startTooltip: 'Speak',
      stopTooltip: 'Stop voice conversation',
      noSpeech: 'No speech heard. Please try again.',
      micPermission: 'Please allow microphone access.',
      network: 'Network problem.',
      speechErrorPrefix: 'Voice error',
      notUnderstood: 'Could not understand speech. Please try again.',
      voiceServerProblemPrefix: 'Voice server problem',
      micStartProblemPrefix: 'Could not start microphone',
    },

    suggestedQuestions: [
      'Find Indian restaurants near Seattle',
      'Compare chicken tikka masala prices near Seattle',
      'Find Thai dinner under $25 near Bellevue',
      'Show Italian restaurants with menu items near Seattle',
      'What is the cheapest pad thai near me?',
      'Find American fast food options near Seattle',
      'Show seafood restaurants with good reviews',
      'Find vegetarian Asian dinner options',
    ],

    registerSubtitle:    'Restaurant recommender · menu search · price comparison',
    showTeamDropdown:    false,
    teamDropdownLabel:   '',
    teamDropdownHelper:  '',

    loginTitle:   'Adar Restaurants',
    loginCaption: 'Powered by Adar · Restaurant Food Recommender',
  },

  scheduling: {
    id:            'scheduling',
    appTitle:      'Adar Scheduling',
    name:          'Practice Scheduling Assistant',
    shortName:     'Scheduling',
    subtitle:      'Book, Check, Reschedule & Cancel Appointments',
    logoText:      'Adar',

    primaryColor:  '#2563EB',
    primaryLight:  '#60A5FA',
    primaryDark:   '#1E40AF',
    accentColor:   '#059669',
    accentLight:   '#34D399',
    accentDark:    '#047857',
    bgDefault:     '#F8FAFC',
    bgPaper:       '#FFFFFF',
    textPrimary:   '#1E293B',
    textSecondary: '#64748B',
    divider:       '#E2E8F0',

    fontFamily: '"Inter", "Roboto", "Helvetica Neue", sans-serif',

    // Chat strings
    welcomeMessage:
      "Hi! I'm your scheduling assistant. I can help you book, check, " +
      "reschedule, or cancel an appointment.\n\nWhat would you like to do?",
    placeholder:    'Ask to book, check, or cancel an appointment…',
    typingText:     'Checking availability…',
    clearMessage:   'Session cleared. What would you like to schedule?',
    footerText:     'Powered by Adar',
    evalLabels: {
      accuracy: 'Accuracy',
      completeness: 'Completeness',
      relevance: 'Relevance',
      format: 'Format',
      overall: 'Overall',
      scale: '5',
    },
    voice: {
      lang: 'en-US',
      startTooltip: 'Speak',
      stopTooltip: 'Stop voice conversation',
      noSpeech: 'No speech heard. Please try again.',
      micPermission: 'Please allow microphone access.',
      network: 'Network problem.',
      speechErrorPrefix: 'Voice error',
      notUnderstood: 'Could not understand speech. Please try again.',
      voiceServerProblemPrefix: 'Voice server problem',
      micStartProblemPrefix: 'Could not start microphone',
    },

    // Suggested questions shown on first load
    suggestedQuestions: [
      'What appointment types do you offer?',
      'I need to see a doctor next week',
      'What times are open tomorrow afternoon?',
      'Book a follow-up visit',
      'Cancel my appointment',
      'Reschedule my appointment to next Friday',
    ],

    // Register page
    registerSubtitle:    'Practice scheduling · book, check, and manage appointments',
    showTeamDropdown:    false,
    teamDropdownLabel:   '',
    teamDropdownHelper:  '',

    // Login page
    loginTitle:   'Adar Scheduling',
    loginCaption: 'Powered by Adar · Practice Scheduling Assistant',
  },
}

const tenant = TENANTS[_domain] || TENANTS.arcl
export default tenant