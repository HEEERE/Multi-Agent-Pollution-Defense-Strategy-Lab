import { useCallback, useEffect, useRef, useState } from "react";

export function useDraggable() {
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const anchor = useRef({ x: 0, y: 0 });

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setDragging(true);
      anchor.current = { x: e.clientX - offset.x, y: e.clientY - offset.y };
    },
    [offset],
  );

  useEffect(() => {
    if (!dragging) return;
    const onMouseMove = (e: MouseEvent) => {
      setOffset({ x: e.clientX - anchor.current.x, y: e.clientY - anchor.current.y });
    };
    const onMouseUp = () => setDragging(false);
    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
    return () => {
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };
  }, [dragging]);

  return { offset, onMouseDown, dragging };
}
