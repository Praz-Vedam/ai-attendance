"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import Webcam from "react-webcam";

import { FaceGuide } from "@/components/FaceGuide";
import { registerStudent } from "@/lib/api";

const REQUIRED_IMAGES = 3;

const CAPTURE_STEPS = [
  {
    key: "front",
    instruction: "Look straight at the camera",
    captured: "Front image captured",
  },
  {
    key: "left",
    instruction: "Tilt your head slightly to your left",
    captured: "Left image captured",
  },
  {
    key: "right",
    instruction: "Tilt your head slightly to your right",
    captured: "Right image captured",
  },
] as const;

export default function RegisterStudentPage() {
  const router = useRouter();
  const webcamRef = useRef<Webcam>(null);

  const [name, setName] = useState("");
  const [frontImageBlob, setFrontImageBlob] = useState<Blob | null>(null);
  const [leftImageBlob, setLeftImageBlob] = useState<Blob | null>(null);
  const [rightImageBlob, setRightImageBlob] = useState<Blob | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [registeredId, setRegisteredId] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState(0);
  const [captureMessage, setCaptureMessage] = useState("");

  const images = [frontImageBlob, leftImageBlob, rightImageBlob];
  const completedImages = images.filter(Boolean).length;
  const imagesComplete = completedImages >= REQUIRED_IMAGES;
  const currentStepConfig =
    CAPTURE_STEPS[Math.min(currentStep, REQUIRED_IMAGES - 1)];

  const captureCurrentImage = async () => {
    if (loading || imagesComplete) return;

    const screenshot = webcamRef.current?.getScreenshot();
    if (!screenshot) {
      setMessage("Could not capture from webcam. Please allow camera access and try again.");
      return;
    }

    const blob = await fetch(screenshot).then((res) => res.blob());

    if (currentStep === 0) {
      setFrontImageBlob(blob);
    } else if (currentStep === 1) {
      setLeftImageBlob(blob);
    } else {
      setRightImageBlob(blob);
    }

    setCaptureMessage(`✓ ${CAPTURE_STEPS[currentStep].captured}`);
    setMessage("");
    setCurrentStep((prev) => Math.min(prev + 1, REQUIRED_IMAGES));
  };

  const handleRegister = async () => {
    if (!name.trim()) {
      setMessage("Enter your name");
      return;
    }

    if (!frontImageBlob || !leftImageBlob || !rightImageBlob) {
      setMessage(
        `Capture ${REQUIRED_IMAGES} face images (${completedImages}/${REQUIRED_IMAGES})`
      );
      return;
    }

    setLoading(true);
    setMessage("");
    setRegisteredId(null);

    try {
      const data = await registerStudent(name, {
        front: frontImageBlob,
        left: leftImageBlob,
        right: rightImageBlob,
      });
      if (!data.success || !data.id) {
        setMessage(data.message);
        setLoading(false);
        return;
      }

      setRegisteredId(data.id);
      setMessage(data.message);
    } catch {
      setMessage("Registration failed. Is the backend running?");
    }

    setLoading(false);
  };

  const resetImages = () => {
    setFrontImageBlob(null);
    setLeftImageBlob(null);
    setRightImageBlob(null);
    setCurrentStep(0);
    setCaptureMessage("");
    setMessage("");
  };

  return (
    <main className="min-h-screen bg-black text-white px-6 py-10">
      <div className="max-w-lg mx-auto space-y-8">
        <div>
          <Link href="/" className="text-zinc-400 hover:text-white text-sm">
            ← Home
          </Link>
          <h1 className="text-4xl font-bold mt-4 mb-2">Register student</h1>
          <p className="text-zinc-400">
            Enter your name and complete the guided face scans. You will receive
            a student ID when registration succeeds.
          </p>
        </div>

        {registeredId ? (
          <div className="bg-zinc-900 border border-green-500/50 rounded-3xl p-8 space-y-6">
            <p className="text-green-400 font-semibold text-lg">
              Registration successful
            </p>
            <div>
              <p className="text-zinc-400 text-sm mb-2">Your student ID</p>
              <p className="font-mono text-xl break-all bg-zinc-800 px-4 py-3 rounded-xl">
                {registeredId}
              </p>
              <p className="text-zinc-500 text-sm mt-3">
                Save this ID. Teachers can use it to find you on the roster.
              </p>
            </div>
            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => router.push("/dashboard")}
                className="bg-blue-600 hover:bg-blue-500 transition px-6 py-3 rounded-2xl font-semibold"
              >
                Go to dashboard
              </button>
              <button
                type="button"
                onClick={() => router.push("/login")}
                className="bg-zinc-700 hover:bg-zinc-600 transition px-6 py-3 rounded-2xl font-semibold"
              >
                Sign in later
              </button>
            </div>
          </div>
        ) : (
          <div className="bg-zinc-900 border border-zinc-800 rounded-3xl p-8 space-y-5">
            <div>
              <label className="block text-sm text-zinc-400 mb-2">
                Your name
              </label>
              <input
                type="text"
                required
                placeholder="Full name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-2xl px-5 py-4 outline-none"
              />
            </div>

            <div className="text-center">
              <p className="text-zinc-400 text-sm mb-1">
                Image {Math.min(completedImages + 1, REQUIRED_IMAGES)}/{REQUIRED_IMAGES}
              </p>
              <p className="text-xl font-semibold">
                {imagesComplete
                  ? "Registration images captured successfully"
                  : currentStepConfig.instruction}
              </p>
            </div>

            <div className="relative overflow-hidden rounded-3xl border border-zinc-700">
              <Webcam
                ref={webcamRef}
                screenshotFormat="image/jpeg"
                className="w-full block"
                videoConstraints={{
                  width: { ideal: 1280 },
                  height: { ideal: 720 },
                  facingMode: "user",
                }}
                onUserMediaError={() => {
                  setMessage("Camera permission denied. Please allow camera access to register.");
                }}
              />
              {!imagesComplete && <FaceGuide step={currentStep} />}
            </div>

            <div className="text-center py-4 min-h-14">
              {imagesComplete ? (
                <p className="text-green-400 font-semibold text-lg">
                  ✓ Registration images captured successfully
                </p>
              ) : captureMessage ? (
                <p className="text-green-400 text-sm">{captureMessage}</p>
              ) : null}
            </div>

            <div className="flex flex-wrap gap-3">
              {!imagesComplete && (
                <button
                  type="button"
                  onClick={captureCurrentImage}
                  disabled={loading}
                  className="bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition px-5 py-3 rounded-2xl font-semibold"
                >
                  Capture Image
                </button>
              )}
              <button
                type="button"
                onClick={resetImages}
                disabled={loading || completedImages === 0}
                className="text-zinc-400 hover:text-white text-sm px-2"
              >
                Clear images
              </button>
            </div>

            {completedImages > 0 && (
              <p className="text-green-400 text-sm">
                {completedImages} image{completedImages === 1 ? "" : "s"} ready
              </p>
            )}

            <button
              type="button"
              onClick={handleRegister}
              disabled={loading || !imagesComplete}
              className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition py-4 rounded-2xl font-semibold"
            >
              {loading ? "Registering…" : "Register student"}
            </button>
          </div>
        )}

        {!registeredId && (
          <p className="text-zinc-500 text-sm text-center">
            Already enrolled?{" "}
            <Link href="/login" className="text-blue-400 hover:text-blue-300">
              Sign in with your face
            </Link>
          </p>
        )}

        {message && !registeredId && (
          <p className="text-red-400 text-center font-medium">{message}</p>
        )}
      </div>
    </main>
  );
}
