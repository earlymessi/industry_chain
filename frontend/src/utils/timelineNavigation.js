// Navigation changes the viewport only; all times use Unix seconds.
export function liveTimelineWindow(now, hours) {
  const span = Math.max(60, Number(hours) * 3600)
  return { begin: now - span * .2, end: now + span * .8 }
}

export function shiftTimelineWindow(window, seconds) {
  return { begin: window.begin + seconds, end: window.end + seconds }
}

export function dragTimelineWindow(window, pixels, plotWidth) {
  return shiftTimelineWindow(window, -pixels / Math.max(1, plotWidth) * (window.end - window.begin))
}
