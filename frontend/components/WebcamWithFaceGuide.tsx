"use client";

import React, { useRef, useEffect, useState } from "react";
import Webcam from "react-webcam";
import { useFaceDetection } from "@/lib/useFaceDetection";
import { FacePositioningGuide } from "./FacePositioningGuide";

interface WebcamWithFaceGuideProps {
  webcamRef: React.RefObject<Webcam>;
  context?: "register" | "attendance";
  className?: string;
}

export function WebcamWithFaceGuide({
  webcamRef,
  context = "register",
  className = "",
}: WebcamWithFaceGuideProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [dimensions, setDimensions] = useState({ width: 0, height: 0 });

  const faceDetectionState = useFaceDetection(videoRef, context);

  useEffect(() => {
    if (!webcamRef.current?.video) return;

    const video = webcamRef.current.video;
    videoRef.current = video;

    const updateDimensions = () => {
      if (video.videoWidth && video.videoHeight) {
        setDimensions({
          width: video.videoWidth,
          height: video.videoHeight,
        });
      }
    };

    video.addEventListener("play", updateDimensions);
    updateDimensions();

    return () => {
      video.removeEventListener("play", updateDimensions);
    };
  }, [webcamRef]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleResize = () => {
      const rect = container.getBoundingClientRect();
      setDimensions({
        width: rect.width,
        height: rect.height,
      });
    };

    const resizeObserver = new ResizeObserver(handleResize);
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
    };
  }, []);

  return (
    <div ref={containerRef} className={`relative w-full ${className}`}>
      <Webcam
        ref={webcamRef}
        screenshotFormat="image/jpeg"
        className={`rounded-3xl w-full border border-zinc-700 block`}
        style={{ display: "block" }}
      />
      {dimensions.width > 0 && dimensions.height > 0 && (
        <FacePositioningGuide
          state={faceDetectionState}
          containerWidth={dimensions.width}
          containerHeight={dimensions.height}
        />
      )}
    </div>
  );
}
