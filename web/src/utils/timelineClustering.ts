import type { SessionModel } from '../types';

export interface ChildSegment {
  app: string;
  title: string;
  start: string;
  end: string;
  duration_seconds: number;
  category_name?: string | null;
  category_color?: string | null;
  category_type?: string | null;
  is_interruption?: boolean;
}

export interface AppBreakdownSummary {
  app: string;
  seconds: number;
  pct: number;
  label: string;
}

export interface TimelineClusterModel {
  cluster_id: string;
  label: string;
  cluster_type: 'single' | 'absorbed' | 'mixed' | 'category';
  dominant_app: string;
  dominant_category?: string | null;
  category_color: string;
  category_type: string;
  start: string;
  end: string;
  duration_seconds: number;
  interruption_count: number;
  child_segments: ChildSegment[];
  app_breakdown: AppBreakdownSummary[];
  is_idle: boolean;
  original_session?: SessionModel;
}

function parseSeconds(isoStr: string): number {
  try {
    const d = new Date(isoStr);
    return d.getTime() / 1000;
  } catch {
    return 0;
  }
}

function formatDurationShort(sec: number): string {
  if (sec < 60) return `${sec}s`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

function calculateAppBreakdown(segments: ChildSegment[]): AppBreakdownSummary[] {
  const totals: Record<string, number> = {};
  for (const s of segments) {
    const name = s.app || 'Unknown';
    totals[name] = (totals[name] || 0) + Math.max(0, s.duration_seconds);
  }
  const sum = Object.values(totals).reduce((a, b) => a + b, 0) || 1;
  return Object.entries(totals)
    .sort((a, b) => b[1] - a[1])
    .map(([app, sec]) => ({
      app,
      seconds: sec,
      pct: Math.round((sec / sum) * 100),
      label: formatDurationShort(sec),
    }));
}

export function isBrowserApp(app?: string | null): boolean {
  const a = (app || '').toLowerCase();
  return a.includes('chrome') || a.includes('edge') || a.includes('firefox') || a.includes('brave') || a.includes('opera') || a.includes('vivaldi') || a.includes('chromium');
}

export function getSessionSemanticDomain(session: ChildSegment | SessionModel): string {
  const app = (session.app || '').toLowerCase().trim();
  const title = (session.title || '').toLowerCase().trim();
  const catName = (session.category_name || '').toLowerCase().trim();
  const catType = (session.category_type || '').toLowerCase().trim();
  const url = ('url' in session && session.url ? session.url : '').toLowerCase().trim();

  // 1. System Overlays & Windows desktop shell utilities
  const systemApps = new Set([
    'explorer.exe',
    'explorer',
    'shellexperiencehost.exe',
    'searchapp.exe',
    'taskmgr.exe',
    'systemsettings.exe',
    'lockapp.exe',
    'applicationframehost.exe',
  ]);
  if (systemApps.has(app) || title.includes('notification center') || title.includes('quick settings')) {
    return 'system_overlay';
  }
  if (catName.includes('utilities & system') || catName === 'system') {
    return 'system_overlay';
  }

  // 2. Entertainment, Media & Gaming
  const mediaApps = new Set(['spotify.exe', 'spotify', 'vlc.exe', 'vlc', 'steam.exe', 'steam', 'netflix.exe', 'netflix']);
  const gamingKeywords = [
    'valorant',
    'cyberpunk',
    'csgo',
    'minecraft',
    'standoff',
    'roblox',
    'chess.com',
    'steam',
    'gameplay',
    'fps',
    'clutch',
    'ace',
    'twitch',
    'gaming',
  ];
  const entertainmentKeywords = [
    'youtube',
    'netflix',
    'spotify',
    'twitch',
    'vimeo',
    'prime video',
    'disney',
    'hotstar',
    'crunchyroll',
    '#shorts',
    '#gaming',
    'trailer',
    'episode',
    'music',
    'lofi',
    'video',
  ];

  if (mediaApps.has(app) || app.includes('valorant') || app.includes('steam') || app.includes('epicgames')) {
    return 'entertainment';
  }
  if (catName.includes('entertainment') || catName.includes('gaming') || (catType === 'distraction' && !catName.includes('social') && !catName.includes('browse'))) {
    if (['twitter', 'x.com', 'reddit', 'instagram', 'facebook', 'linkedin'].some((sk) => title.includes(sk) || url.includes(sk) || app.includes(sk))) {
      return 'social';
    }
    return 'entertainment';
  }
  if (entertainmentKeywords.some((emk) => title.includes(emk) || url.includes(emk))) {
    return 'entertainment';
  }
  if (gamingKeywords.some((gk) => title.includes(gk) || url.includes(gk))) {
    return 'entertainment';
  }

  // 3. Coding & Software Development
  const codingApps = new Set([
    'code.exe',
    'code',
    'cursor.exe',
    'cursor',
    'pycharm64.exe',
    'pycharm.exe',
    'pycharm',
    'idea64.exe',
    'idea.exe',
    'devenv.exe',
    'sublime_text.exe',
    'nvim.exe',
  ]);
  const terminalApps = new Set([
    'cmd.exe',
    'powershell.exe',
    'pwsh.exe',
    'windowsterminal.exe',
    'bash.exe',
    'git-bash.exe',
    'terminal',
  ]);

  if (codingApps.has(app) || app.includes('cursor') || app.includes('pycharm') || app.includes('visual studio')) {
    return 'coding';
  }
  if (catName.includes('code') || catName.includes('develop') || catName.includes('programming')) {
    return 'coding';
  }
  if (terminalApps.has(app) || app.includes('terminal') || app.includes('powershell') || app === 'python.exe' || app === 'node.exe' || app === 'cargo.exe') {
    return 'coding';
  }
  if (['github.com', 'gitlab.com', 'localhost', '127.0.0.1', 'fastapi', 'vue', 'react', 'vite'].some((dk) => title.includes(dk) || url.includes(dk))) {
    return 'coding';
  }

  // 4. Technical Research & Documentation
  const researchKeywords = [
    'docs',
    'documentation',
    'stackoverflow',
    'github',
    'api reference',
    'api',
    'mdn',
    'tutorial',
    'guide',
    'manual',
    'arxiv',
    'paper',
    'cheat sheet',
    'pypi',
    'npm',
  ];
  if (catName.includes('research') || catName.includes('learn') || catName.includes('study') || catName.includes('education')) {
    return 'research';
  }
  if (researchKeywords.some((rk) => title.includes(rk) || url.includes(rk))) {
    return 'research';
  }

  // 5. Team Communication & Meetings
  const commApps = new Set([
    'slack.exe',
    'slack',
    'discord.exe',
    'discord',
    'teams.exe',
    'teams',
    'whatsapp.exe',
    'whatsapp.root.exe',
    'whatsapp',
    'telegram.exe',
    'telegram',
    'zoom.exe',
    'zoom',
    'outlook.exe',
    'thunderbird.exe',
  ]);
  if (commApps.has(app) || ['slack', 'discord', 'teams', 'whatsapp', 'telegram'].some((ca) => app.includes(ca))) {
    return 'communication';
  }
  if (catName.includes('communi') || catName.includes('meeting') || catName.includes('chat') || catName.includes('messaging')) {
    return 'communication';
  }

  // 6. Planning & Organization
  const planApps = new Set(['notion.exe', 'notion', 'obsidian.exe', 'obsidian', 'excel.exe', 'winword.exe', 'onenote.exe']);
  if (planApps.has(app) || ['notion', 'obsidian', 'trello', 'jira'].some((pa) => app.includes(pa))) {
    return 'planning';
  }
  if (catName.includes('plan') || catName.includes('organi') || catName.includes('manage')) {
    return 'planning';
  }

  // 7. Social & Web Browsing
  if (catName.includes('social') || ['twitter', 'x.com', 'reddit', 'instagram', 'facebook', 'linkedin'].some((sk) => title.includes(sk) || url.includes(sk))) {
    return 'social';
  }

  return 'other';
}

export function getDomainPurpose(dom: string): string {
  if (['coding', 'research', 'communication', 'planning', 'work'].includes(dom)) {
    return 'work';
  }
  if (['entertainment', 'social', 'distraction'].includes(dom)) {
    return 'distraction';
  }
  return 'neutral';
}

export function areDomainsCompatible(dom1: string, dom2: string): boolean {
  if (dom1 === dom2) return true;
  if (dom1 === 'system_overlay' || dom2 === 'system_overlay') return true;
  const p1 = getDomainPurpose(dom1);
  const p2 = getDomainPurpose(dom2);
  if (p1 !== p2 && p1 !== 'neutral' && p2 !== 'neutral') {
    return false;
  }
  if (p1 === 'work' && p2 === 'work') return true;
  if (p1 === 'distraction' && p2 === 'distraction') return true;
  return true;
}

export function inferClusterMetadata(segments: ChildSegment[]): {
  label: string;
  categoryName: string;
  categoryColor: string;
  categoryType: string;
} {
  if (!segments || segments.length === 0) {
    return {
      label: 'Mixed Activity',
      categoryName: 'Task Switching',
      categoryColor: '#8065FF',
      categoryType: 'work',
    };
  }

  const numSwitches = segments.length;
  const totalDur = segments.reduce((sum, s) => sum + Math.max(0, s.duration_seconds || 0), 0) || 1;

  // Accumulate durations by category and domain
  const catDurations: Record<string, number> = {};
  const catColors: Record<string, string> = {};
  const catTypes: Record<string, string> = {};
  const domDurations: Record<string, number> = {};

  for (const s of segments) {
    const cat = s.category_name || 'Other / Needs Review';
    const dur = Math.max(0, s.duration_seconds || 0);
    catDurations[cat] = (catDurations[cat] || 0) + dur;
    if (s.category_color) catColors[cat] = s.category_color;
    if (s.category_type) catTypes[cat] = s.category_type;

    const dom = getSessionSemanticDomain(s);
    domDurations[dom] = (domDurations[dom] || 0) + dur;
  }

  const sortedCats = Object.entries(catDurations).sort((a, b) => b[1] - a[1]);
  const [dominantCat, dominantCatDur] = sortedCats[0];
  const dominantCatPct = dominantCatDur / totalDur;

  const sortedDoms = Object.entries(domDurations).sort((a, b) => b[1] - a[1]);
  let [dominantDom] = sortedDoms[0];
  if (dominantDom === 'system_overlay' && sortedDoms.length > 1) {
    dominantDom = sortedDoms[1][0];
  }

  const allTitles = segments.map((s) => s.title || '');
  const codingApps = new Set(['code.exe', 'code', 'cursor.exe', 'cursor', 'pycharm64.exe', 'pycharm.exe', 'idea64.exe', 'idea.exe', 'devenv.exe', 'sublime_text.exe', 'nvim.exe']);
  const terminalApps = new Set(['cmd.exe', 'powershell.exe', 'pwsh.exe', 'windowsterminal.exe', 'bash.exe', 'git-bash.exe', 'terminal']);

  // Check multi-domain task switching (e.g. Dev + Chat + General Browser)
  const devCount = segments.filter((s) => getSessionSemanticDomain(s) === 'coding').length;
  const commCount = segments.filter((s) => getSessionSemanticDomain(s) === 'communication').length;
  const mediaCount = segments.filter((s) => getSessionSemanticDomain(s) === 'entertainment').length;
  const browserOtherCount = segments.filter((s) => isBrowserApp(s.app) && !['coding', 'research', 'entertainment'].includes(getSessionSemanticDomain(s))).length;
  const distinctDomains = [devCount, commCount, mediaCount, browserOtherCount].filter((cnt) => cnt > 0).length;

  if (distinctDomains >= 3) {
    return {
      label: `Mixed Activity (${numSwitches} switches)`,
      categoryName: 'Task Switching',
      categoryColor: '#8065FF',
      categoryType: 'work',
    };
  }

  // -------------------------------------------------------------------------
  // Case 1: Dominant Domain is ENTERTAINMENT (or category is Entertainment & Media)
  // -------------------------------------------------------------------------
  if (dominantDom === 'entertainment' || dominantCat.toLowerCase().includes('entertainment') || dominantCat.toLowerCase().includes('gaming')) {
    const dynCat = 'Entertainment & Media';
    const dynColor = catColors[dominantCat] || '#FA5275';
    const dynType = 'distraction';

    const gamingKw = ['valorant', 'gaming', 'game', 'standoff', 'cyberpunk', 'chess', 'steam', 'fps', 'clutch', 'ace', 'bgmi', 'r6', 'fortnite'];
    const hasGaming = allTitles.some((t) => gamingKw.some((gk) => t.toLowerCase().includes(gk)));
    const hasShorts = allTitles.some((t) => t.toLowerCase().includes('#shorts') || t.toLowerCase().includes('shorts'));
    const hasMusic = allTitles.some((t) => ['music', 'lofi', 'spotify', 'soundtrack', 'song'].some((mk) => t.toLowerCase().includes(mk)));

    let label: string;
    if (hasGaming && hasShorts) {
      label = `Entertainment — YouTube Gaming Shorts (${numSwitches} switches)`;
    } else if (hasGaming) {
      label = `Gaming & Entertainment (${numSwitches} switches)`;
    } else if (segments.some((s) => (s.title && (s.title.toLowerCase().includes('youtube') || s.title.toLowerCase().includes('video') || s.title.toLowerCase().includes('movie'))) || (s.app && s.app.toLowerCase().includes('vlc')))) {
      label = `Video & Media Watching (${numSwitches} switches)`;
    } else if (hasMusic) {
      label = `Music & Audio Listening (${numSwitches} switches)`;
    } else {
      label = `Video & Media Watching (${numSwitches} switches)`;
    }

    return { label, categoryName: dynCat, categoryColor: dynColor, categoryType: dynType };
  }

  // -------------------------------------------------------------------------
  // Case 2: Dominant Domain is CODING (or category is Coding & Development)
  // -------------------------------------------------------------------------
  if (dominantDom === 'coding' || dominantCat.toLowerCase().includes('code') || dominantCat.toLowerCase().includes('develop')) {
    const dynCat = 'Coding & Development';
    const dynColor = catColors[dominantCat] || '#35D68A';
    const dynType = 'focus';

    const codingTitles = segments
      .filter((s) => codingApps.has((s.app || '').toLowerCase()) || terminalApps.has((s.app || '').toLowerCase()) || ['python.exe', 'node.exe'].includes((s.app || '').toLowerCase()))
      .map((s) => (s.title || '').toLowerCase());
    const isDebug = codingTitles.some((t) => ['test', 'pytest', 'debug', 'run', 'build', 'pdb', 'unittest', 'npm run', 'cargo test'].some((kw) => t.includes(kw)));
    const hasTerminal = segments.some((s) => terminalApps.has((s.app || '').toLowerCase()));

    let projectName: string | null = null;
    for (const s of segments) {
      if (codingApps.has((s.app || '').toLowerCase()) && s.title) {
        const m = s.title.match(/-\s*([^-]+?)\s*-\s*Visual Studio/i);
        if (m && m[1]) {
          const cand = m[1].trim();
          if (cand && !cand.toLowerCase().includes('visual studio')) {
            projectName = cand;
            break;
          }
        }
      }
    }

    let label: string;
    if (projectName) {
      label = isDebug || hasTerminal ? `Coding & Debugging — ${projectName}` : `Project Development — ${projectName}`;
    } else if (isDebug || hasTerminal) {
      label = `Coding & Debugging (${numSwitches} switches)`;
    } else {
      label = `Software Development (${numSwitches} switches)`;
    }

    return { label, categoryName: dynCat, categoryColor: dynColor, categoryType: dynType };
  }

  // -------------------------------------------------------------------------
  // Case 3: Dominant Domain is RESEARCH (or category is Research & Learning)
  // -------------------------------------------------------------------------
  if (dominantDom === 'research' || dominantCat.toLowerCase().includes('research') || dominantCat.toLowerCase().includes('learn')) {
    const dynCat = 'Research & Learning';
    const dynColor = catColors[dominantCat] || '#38BDF8';
    const dynType = 'focus';

    let subject: string | null = null;
    for (const s of segments) {
      const t = (s.title || '').toLowerCase();
      if (t.includes('documentation') || t.includes('docs') || t.includes('stackoverflow')) {
        const cleanT = (s.title || '').split(' - ')[0].split(' | ')[0].trim();
        if (cleanT && cleanT.length <= 40) {
          subject = cleanT;
          break;
        }
      }
    }

    const label = subject ? `Technical Research & Documentation — ${subject}` : `Technical Research & Documentation (${numSwitches} switches)`;
    return { label, categoryName: dynCat, categoryColor: dynColor, categoryType: dynType };
  }

  // -------------------------------------------------------------------------
  // Case 4: Dominant Domain is COMMUNICATION (or category is Communication & Meetings)
  // -------------------------------------------------------------------------
  if (dominantDom === 'communication' || dominantCat.toLowerCase().includes('communi') || dominantCat.toLowerCase().includes('meet')) {
    return {
      label: `Team Communication & Messaging (${numSwitches} switches)`,
      categoryName: 'Communication & Meetings',
      categoryColor: catColors[dominantCat] || '#818CF8',
      categoryType: 'work',
    };
  }

  // -------------------------------------------------------------------------
  // Case 5: Dominant Domain is PLANNING (or category is Planning & Organization)
  // -------------------------------------------------------------------------
  if (dominantDom === 'planning' || dominantCat.toLowerCase().includes('plan') || dominantCat.toLowerCase().includes('organi')) {
    return {
      label: `Planning & Documentation (${numSwitches} switches)`,
      categoryName: 'Planning & Organization',
      categoryColor: catColors[dominantCat] || '#F59E0B',
      categoryType: 'work',
    };
  }

  // -------------------------------------------------------------------------
  // Case 6: Dominant Domain is SOCIAL (or category is Social & Browsing)
  // -------------------------------------------------------------------------
  if (dominantDom === 'social' || dominantCat.toLowerCase().includes('social')) {
    return {
      label: `Social & Web Browsing (${numSwitches} switches)`,
      categoryName: 'Social & Browsing',
      categoryColor: catColors[dominantCat] || '#EC4899',
      categoryType: 'distraction',
    };
  }

  // -------------------------------------------------------------------------
  // Case 7: Truly Mixed Activity / Task Switching
  // -------------------------------------------------------------------------
  if (dominantCatPct >= 0.50 && !['Other / Needs Review', 'Unknown', 'Other'].includes(dominantCat)) {
    return {
      label: `Mixed Activity — ${dominantCat} (${numSwitches} switches)`,
      categoryName: dominantCat,
      categoryColor: catColors[dominantCat] || '#8065FF',
      categoryType: catTypes[dominantCat] || 'work',
    };
  }

  return {
    label: `Mixed Activity (${numSwitches} switches)`,
    categoryName: 'Task Switching',
    categoryColor: '#8065FF',
    categoryType: 'work',
  };
}

export function clusterTimelineSessions(
  sessions: SessionModel[],
  debounceThresholdSeconds = 60,
  mixedThresholdSeconds = 180,
  groupByCategory = false
): TimelineClusterModel[] {
  if (!sessions || sessions.length === 0) return [];

  const valid = sessions.filter((s) => s.start && s.end);
  const clusters: TimelineClusterModel[] = [];
  const n = valid.length;
  let i = 0;

  if (groupByCategory) {
    while (i < n) {
      const curr = valid[i];
      const catName = curr.category_name || (curr.kind === 'idle' ? 'Idle' : 'Other');
      const catColor = curr.category_color || (curr.kind === 'idle' ? '#5A6679' : '#8065FF');
      const catType = curr.category_type || (curr.kind === 'idle' ? 'break' : 'work');
      let j = i;
      const segs: ChildSegment[] = [];
      let totalDur = 0;

      while (j < n) {
        const item = valid[j];
        const itemCatName = item.category_name || (item.kind === 'idle' ? 'Idle' : 'Other');
        if (itemCatName !== catName) break;
        const dur = Math.max(1, item.duration_seconds || 0);
        segs.push({
          app: item.app || 'Unknown',
          title: item.title || '',
          start: item.start,
          end: item.end,
          duration_seconds: dur,
          category_name: itemCatName,
          category_color: item.category_color || catColor,
          category_type: item.category_type || catType,
        });
        totalDur += dur;
        j++;
      }

      clusters.push({
        cluster_id: `cat_${i}`,
        label: catName,
        cluster_type: 'category',
        dominant_app: segs[0]?.app || catName,
        dominant_category: catName,
        category_color: catColor,
        category_type: catType,
        start: segs[0].start,
        end: segs[segs.length - 1].end,
        duration_seconds: totalDur,
        interruption_count: 0,
        child_segments: segs,
        app_breakdown: calculateAppBreakdown(segs),
        is_idle: catName.toLowerCase() === 'idle',
        original_session: curr,
      });
      i = j;
    }
    return clusters;
  }

  while (i < n) {
    const curr = valid[i];
    const currApp = curr.app || 'Unknown';
    const currKind = curr.kind || 'active';
    const currCatName = curr.category_name || 'Other';
    const currCatColor = curr.category_color || '#8065FF';
    const currCatType = curr.category_type || 'work';
    const currDur = Math.max(0, curr.duration_seconds || 0);

    // 1. Idle sessions are preserved as isolated blocks
    if (currKind === 'idle') {
      const seg: ChildSegment = {
        app: currApp,
        title: curr.title || 'Idle',
        start: curr.start,
        end: curr.end,
        duration_seconds: currDur,
        category_name: 'Idle',
        category_color: '#5A6679',
        category_type: 'break',
        is_interruption: false,
      };
      clusters.push({
        cluster_id: `idle_${i}`,
        label: 'Idle / Away',
        cluster_type: 'single',
        dominant_app: 'Idle',
        dominant_category: 'Idle',
        category_color: '#5A6679',
        category_type: 'break',
        start: curr.start,
        end: curr.end,
        duration_seconds: currDur,
        interruption_count: 0,
        child_segments: [seg],
        app_breakdown: [{ app: 'Idle', seconds: currDur, pct: 100, label: formatDurationShort(currDur) }],
        is_idle: true,
        original_session: curr,
      });
      i++;
      continue;
    }

    // 2. Excursion Debounce (Rule 1): A -> B -> A where B < debounceThresholdSeconds (< 60s)
    let absorbed = false;
    if (i + 2 < n) {
      const mid = valid[i + 1];
      const third = valid[i + 2];
      const midApp = mid.app || 'Unknown';
      const thirdApp = third.app || 'Unknown';
      const midDur = Math.max(0, mid.duration_seconds || 0);
      const midKind = mid.kind || 'active';
      const thirdKind = third.kind || 'active';

      const gap1 = Math.abs(parseSeconds(mid.start) - parseSeconds(curr.end));
      const gap2 = Math.abs(parseSeconds(third.start) - parseSeconds(mid.end));

      // For browser apps, verify return to compatible context
      let sameContext = true;
      if (isBrowserApp(currApp)) {
        sameContext = areDomainsCompatible(getSessionSemanticDomain(curr), getSessionSemanticDomain(third));
      }

      if (
        thirdApp.toLowerCase() === currApp.toLowerCase() &&
        midApp.toLowerCase() !== currApp.toLowerCase() &&
        midDur < debounceThresholdSeconds &&
        midKind !== 'idle' &&
        thirdKind !== 'idle' &&
        gap1 < 10 &&
        gap2 < 10 &&
        sameContext
      ) {
        const seg1: ChildSegment = {
          app: currApp,
          title: curr.title || '',
          start: curr.start,
          end: curr.end,
          duration_seconds: currDur,
          category_name: currCatName,
          category_color: currCatColor,
          category_type: currCatType,
          is_interruption: false,
        };
        const seg2: ChildSegment = {
          app: midApp,
          title: mid.title || '',
          start: mid.start,
          end: mid.end,
          duration_seconds: midDur,
          category_name: mid.category_name,
          category_color: mid.category_color,
          category_type: mid.category_type,
          is_interruption: true,
        };
        const seg3: ChildSegment = {
          app: thirdApp,
          title: third.title || '',
          start: third.start,
          end: third.end,
          duration_seconds: Math.max(0, third.duration_seconds || 0),
          category_name: third.category_name || currCatName,
          category_color: third.category_color || currCatColor,
          category_type: third.category_type || currCatType,
          is_interruption: false,
        };
        const totalDur = currDur + midDur + seg3.duration_seconds;
        const segs = [seg1, seg2, seg3];
        clusters.push({
          cluster_id: `cluster_${i}`,
          label: currApp.replace('.exe', ''),
          cluster_type: 'absorbed',
          dominant_app: currApp,
          dominant_category: currCatName,
          category_color: currCatColor,
          category_type: currCatType,
          start: curr.start,
          end: third.end,
          duration_seconds: totalDur,
          interruption_count: 1,
          child_segments: segs,
          app_breakdown: calculateAppBreakdown(segs),
          is_idle: false,
          original_session: curr,
        });
        i += 3;
        absorbed = true;
      }
    }

    if (absorbed) continue;

    // 3. Semantic Activity Clustering & Rapid Task Switching:
    let j = i;
    const rapidSegments: ChildSegment[] = [];
    let rapidTotalDur = 0;
    let clusterDomain = getSessionSemanticDomain(curr);

    // If starting with a brief system overlay, anchor to next active session if possible
    if (clusterDomain === 'system_overlay' && i + 1 < n) {
      const nextDom = getSessionSemanticDomain(valid[i + 1]);
      if (nextDom !== 'system_overlay') {
        clusterDomain = nextDom;
      }
    }

    while (j < n) {
      const cand = valid[j];
      const candDur = cand.duration_seconds || 0;
      const candKind = cand.kind || 'active';
      if (candKind === 'idle') break;

      if (j > i) {
        // Never cluster across distinct calendar dates
        if (cand.start.slice(0, 10) !== valid[j - 1].end.slice(0, 10)) break;
        const gap = Math.abs(parseSeconds(cand.start) - parseSeconds(valid[j - 1].end));
        if (gap > 30) break;

        // Sustained session (>= 180s) terminates rapid cluster
        if (candDur >= mixedThresholdSeconds) break;

        // Semantic Boundary Check:
        const candDom = getSessionSemanticDomain(cand);
        if (!areDomainsCompatible(clusterDomain, candDom)) {
          // Check if single transient excursion (< 60s) returning immediately to clusterDomain
          const isTransient =
            candDur < 60 &&
            j + 1 < n &&
            areDomainsCompatible(clusterDomain, getSessionSemanticDomain(valid[j + 1])) &&
            valid[j + 1].kind !== 'idle';

          if (['entertainment', 'social'].includes(candDom) && (candDur >= 30 || !isTransient)) {
            break;
          }
          if (!isTransient) {
            break;
          }
        }
      }

      rapidSegments.push({
        app: cand.app || 'Unknown',
        title: cand.title || '',
        start: cand.start,
        end: cand.end,
        duration_seconds: candDur,
        category_name: cand.category_name,
        category_color: cand.category_color,
        category_type: cand.category_type,
        is_interruption: j > i && getSessionSemanticDomain(cand) !== clusterDomain && getSessionSemanticDomain(cand) !== 'system_overlay',
      });
      rapidTotalDur += candDur;
      j++;
    }

    if (rapidSegments.length >= 3 && rapidTotalDur >= 60) {
      const breakdown = calculateAppBreakdown(rapidSegments);
      const dominant = breakdown[0]?.app || 'Mixed';
      const meta = inferClusterMetadata(rapidSegments);
      clusters.push({
        cluster_id: `mixed_${i}`,
        label: meta.label,
        cluster_type: 'mixed',
        dominant_app: dominant,
        dominant_category: meta.categoryName,
        category_color: meta.categoryColor,
        category_type: meta.categoryType,
        start: rapidSegments[0].start,
        end: rapidSegments[rapidSegments.length - 1].end,
        duration_seconds: rapidTotalDur,
        interruption_count: rapidSegments.filter((seg) => seg.is_interruption).length,
        child_segments: rapidSegments,
        app_breakdown: breakdown,
        is_idle: false,
        original_session: valid[i],
      });
      i = j;
      continue;
    }

    // 4. Default: Single standalone session
    const singleSeg: ChildSegment = {
      app: currApp,
      title: curr.title || '',
      start: curr.start,
      end: curr.end,
      duration_seconds: currDur,
      category_name: currCatName,
      category_color: currCatColor,
      category_type: currCatType,
      is_interruption: false,
    };
    clusters.push({
      cluster_id: `single_${i}`,
      label: currApp.replace('.exe', ''),
      cluster_type: 'single',
      dominant_app: currApp,
      dominant_category: currCatName,
      category_color: currCatColor,
      category_type: currCatType,
      start: curr.start,
      end: curr.end,
      duration_seconds: currDur,
      interruption_count: 0,
      child_segments: [singleSeg],
      app_breakdown: [{ app: currApp, seconds: currDur, pct: 100, label: formatDurationShort(currDur) }],
      is_idle: false,
      original_session: curr,
    });
    i++;
  }

  return clusters;
}
