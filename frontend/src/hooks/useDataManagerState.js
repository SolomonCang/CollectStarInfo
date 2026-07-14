import { useReducer, useCallback } from "react";

// ── Initial state ────────────────────────────────────────────────
const initialState = {
  // Filter
  search: "",
  source: "",

  // Data (star-centric)
  stars: [],
  total: 0,
  offset: 0,
  limit: 25,

  // Selection (star names)
  selectedStars: [],
  expandedStar: null, // which star card is expanded for detail

  // Status
  busy: false,
  message: "",
  error: "",

  // Stats
  stats: null,
};

// ── Reducer ──────────────────────────────────────────────────────
function reducer(state, action) {
  switch (action.type) {
    case "SET_FILTER":
      return { ...state, ...action.payload, offset: 0 };
    case "SET_OFFSET":
      return { ...state, offset: action.payload };
    case "SET_LIMIT":
      return { ...state, limit: action.payload, offset: 0 };
    case "SET_BUSY":
      return { ...state, busy: true, error: "", message: "" };
    case "SET_STARS":
      return {
        ...state,
        busy: false,
        stars: action.payload.stars,
        total: action.payload.total,
        offset: action.payload.offset ?? state.offset,
        limit: action.payload.limit ?? state.limit,
        selectedStars: [],
        expandedStar: null,
      };
    case "SET_STATS":
      return { ...state, busy: false, stats: action.payload };
    case "SET_ERROR":
      return { ...state, busy: false, error: action.payload, message: "" };
    case "SET_MESSAGE":
      return { ...state, busy: false, message: action.payload };
    case "TOGGLE_SELECT": {
      const name = action.payload;
      const next = state.selectedStars.includes(name)
        ? state.selectedStars.filter((s) => s !== name)
        : [...state.selectedStars, name];
      return { ...state, selectedStars: next };
    }
    case "SELECT_ALL": {
      const all = state.stars.map((s) => s.normalized);
      if (all.length && state.selectedStars.length === all.length) {
        return { ...state, selectedStars: [] };
      }
      return { ...state, selectedStars: all };
    }
    case "SET_EXPANDED":
      return {
        ...state,
        expandedStar: state.expandedStar === action.payload ? null : action.payload,
      };
    default:
      return state;
  }
}

// ── Hook ─────────────────────────────────────────────────────────
export function useDataManagerState() {
  const [state, dispatch] = useReducer(reducer, initialState);

  const setFilter = useCallback(
    (updates) => dispatch({ type: "SET_FILTER", payload: updates }),
    []
  );
  const setOffset = useCallback((v) => dispatch({ type: "SET_OFFSET", payload: v }), []);
  const setLimit = useCallback((v) => dispatch({ type: "SET_LIMIT", payload: v }), []);
  const toggleSelect = useCallback((name) => dispatch({ type: "TOGGLE_SELECT", payload: name }), []);
  const selectAll = useCallback(() => dispatch({ type: "SELECT_ALL" }), []);
  const toggleExpand = useCallback((name) => dispatch({ type: "SET_EXPANDED", payload: name }), []);

  return {
    ...state,
    setFilter,
    setOffset,
    setLimit,
    toggleSelect,
    selectAll,
    toggleExpand,
    dispatch,
  };
}
