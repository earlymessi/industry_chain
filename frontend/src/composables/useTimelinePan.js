import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { dragTimelineWindow, shiftTimelineWindow } from '../utils/timelineNavigation.js'

export function useTimelinePan(getWindow, navigate, left = 155, right = 20) {
  const element = ref(null), state = reactive({ width: 1120, dragging: false })
  let gesture = null, blockClick = false, observer
  const plotWidth = () => Math.max(1, (element.value?.getBoundingClientRect().width || state.width) - left - right)
  function start(event) {
    if (event.isPrimary === false || event.button !== 0) return
    blockClick = false
    gesture = { id: event.pointerId, x: event.clientX, y: event.clientY, window: { ...getWindow() }, target: event.currentTarget }
  }
  function move(event) {
    if (!gesture || event.pointerId !== gesture.id) return
    const dx = event.clientX - gesture.x, dy = event.clientY - gesture.y
    if (!state.dragging) {
      if (Math.abs(dy) > Math.abs(dx) && Math.abs(dy) > 6) { gesture = null; return }
      if (Math.abs(dx) < 5) return
      state.dragging = true
      gesture.target.setPointerCapture?.(event.pointerId)
    }
    event.preventDefault()
    blockClick = true
    navigate(dragTimelineWindow(gesture.window, dx, plotWidth()))
  }
  function end(event) {
    if (!gesture || (event && event.pointerId !== gesture.id)) return
    const { target, id } = gesture
    gesture = null; state.dragging = false
    if (target.hasPointerCapture?.(id)) target.releasePointerCapture(id)
  }
  function suppressClick(event) {
    if (!blockClick || !event.detail) return
    blockClick = false; event.preventDefault(); event.stopPropagation()
  }
  function step(direction) {
    const window = getWindow()
    navigate(shiftTimelineWindow(window, direction * (window.end - window.begin) * .8))
  }
  function wheel(event) {
    const delta = event.deltaX || (event.shiftKey ? event.deltaY : 0)
    if (!delta) return
    event.preventDefault()
    const window = getWindow()
    navigate(shiftTimelineWindow(window, delta / plotWidth() * (window.end - window.begin)))
  }
  onMounted(() => {
    const resize = () => { if (element.value) state.width = Math.max(360, Math.round(element.value.getBoundingClientRect().width)) }
    resize()
    if (typeof ResizeObserver !== 'undefined') { observer = new ResizeObserver(resize); observer.observe(element.value) }
  })
  onUnmounted(() => { end(); observer?.disconnect() })
  return { element, state, start, move, end, suppressClick, step, wheel }
}
