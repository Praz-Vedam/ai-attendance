"use client";

import React from "react";
import { FaceDetectionState } from "@/lib/useFaceDetection";

interface FacePositioningGuideProps {
  state: FaceDetectionState;
  containerWidth: number;
  containerHeight: number;
}

const GUIDE_WIDTH_RATIO = 0.5;
const GUIDE_HEIGHT_RATIO = 0.6;

export function FacePositioningGuide({
  state,
  containerWidth,
  containerHeight,
}: FacePositioningGuideProps) {
  const guideWidth = containerWidth * GUIDE_WIDTH_RATIO;
  const guideHeight = containerHeight * GUIDE_HEIGHT_RATIO;
  const guideX = (containerWidth - guideWidth) / 2;
  const guideY = (containerHeight - guideHeight) / 2;

  const shoulderWidth = guideWidth * 1.2;
  const shoulderHeight = guideHeight * 0.3;
  const shoulderX = (containerWidth - shoulderWidth) / 2;
  const shoulderY = guideY + guideHeight * 0.8;

  const color = state.aligned ? "#22c55e" : "#ef4444";
  const strokeWidth = 3;

  return (
    <svg
      width={containerWidth}
      height={containerHeight}
      style={{
        position: "absolute",
        top: 0,
        left: 0,
        pointerEvents: "none",
        backgroundColor: "transparent",
      }}
      viewBox={`0 0 ${containerWidth} ${containerHeight}`}
      preserveAspectRatio="none"
    >
      <defs>
        <style>{`
          .guide-overlay {
            opacity: 0.8;
            transition: stroke-color 0.2s ease;
          }
          .guide-icon {
            fill: none;
            stroke: ${color};
            stroke-linecap: round;
            stroke-linejoin: round;
          }
        `}</style>
      </defs>

      {/* Face Oval Guide */}
      <ellipse
        cx={containerWidth / 2}
        cy={containerHeight / 2}
        rx={guideWidth / 2}
        ry={guideHeight / 2}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        className="guide-overlay guide-icon"
      />

      {/* Shoulder Guide - curved outline */}
      <path
        d={`M ${shoulderX} ${shoulderY}
           Q ${containerWidth / 2} ${shoulderY + shoulderHeight * 0.5} ${shoulderX + shoulderWidth} ${shoulderY}
           L ${shoulderX + shoulderWidth * 0.9} ${shoulderY + shoulderHeight}
           L ${shoulderX + shoulderWidth * 0.1} ${shoulderY + shoulderHeight}
           Z`}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        className="guide-overlay guide-icon"
      />

      {/* Center crosshair */}
      <g stroke={color} strokeWidth={2} opacity="0.5">
        <line
          x1={containerWidth / 2 - 20}
          y1={containerHeight / 2}
          x2={containerWidth / 2 + 20}
          y2={containerHeight / 2}
        />
        <line
          x1={containerWidth / 2}
          y1={containerHeight / 2 - 20}
          x2={containerWidth / 2}
          y2={containerHeight / 2 + 20}
        />
      </g>

      {/* Corner guides for frame reference */}
      <g stroke={color} strokeWidth={2} opacity="0.4">
        <line x1={guideX} y1={guideY} x2={guideX + 25} y2={guideY} />
        <line x1={guideX} y1={guideY} x2={guideX} y2={guideY + 25} />

        <line
          x1={guideX + guideWidth}
          y1={guideY}
          x2={guideX + guideWidth - 25}
          y2={guideY}
        />
        <line
          x1={guideX + guideWidth}
          y1={guideY}
          x2={guideX + guideWidth}
          y2={guideY + 25}
        />

        <line
          x1={guideX}
          y1={guideY + guideHeight}
          x2={guideX + 25}
          y2={guideY + guideHeight}
        />
        <line
          x1={guideX}
          y1={guideY + guideHeight}
          x2={guideX}
          y2={guideY + guideHeight - 25}
        />

        <line
          x1={guideX + guideWidth}
          y1={guideY + guideHeight}
          x2={guideX + guideWidth - 25}
          y2={guideY + guideHeight}
        />
        <line
          x1={guideX + guideWidth}
          y1={guideY + guideHeight}
          x2={guideX + guideWidth}
          y2={guideY + guideHeight - 25}
        />
      </g>
    </svg>
  );
}
