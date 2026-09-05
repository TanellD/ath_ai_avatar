import type { Quaternion, Vector3 } from 'three';

interface PoseRuntime {
  poseBase: { props: Record<string, Vector3 | Quaternion> };
  poseAvatar: { props: Record<string, Vector3 | Quaternion> };
  poseDelta: { props: Record<string, { x: number; y: number; z: number }> };
  updatePoseBase(t: number): void;
  updatePoseDelta(): void;
  setPoseFromTemplate(...args: unknown[]): void;
}

/** Install after showAvatar has captured the model's native bone transforms. */
export function stabilizeNonHumanoidPose(head: unknown): () => void {
  const runtime = head as PoseRuntime;
  const nativePose = Object.fromEntries(
    Object.entries(runtime.poseBase.props).map(([key, value]) => [key, value.clone()]),
  );

  // setMood rebuilds the procedural pose queue. Blocking a single queue entry
  // is temporary; human pose templates must never change this model's skeleton.
  runtime.setPoseFromTemplate = () => undefined;
  runtime.updatePoseBase = () => {
    for (const [key, value] of Object.entries(nativePose)) {
      runtime.poseAvatar.props[key]?.copy(value);
    }
  };
  runtime.updatePoseBase(0);

  const updatePoseDelta = runtime.updatePoseDelta.bind(runtime);
  runtime.updatePoseDelta = () => {
    for (const [key, delta] of Object.entries(runtime.poseDelta.props)) {
      if (key === 'Head.quaternion') continue;
      delta.x = delta.y = delta.z = 0;
    }
    updatePoseDelta();
  };

  // TalkingHead applies human hip/feet balancing AFTER updatePoseDelta.
  // opt.update runs after that correction and before rendering.
  return () => {
    const hips = nativePose['Hips.position'];
    if (hips) runtime.poseAvatar.props['Hips.position']?.copy(hips);
  };
}

interface ResizeRuntime {
  resizeobserver: ResizeObserver;
  onResize(): void;
}

/** Replace the vendor observer before it can project a zero-sized container. */
export function guardAvatarResize(head: unknown, mount: HTMLElement): () => void {
  const runtime = head as ResizeRuntime;
  const onResize = () => {
    if (mount.clientWidth > 0 && mount.clientHeight > 0) runtime.onResize();
  };
  runtime.resizeobserver.disconnect();
  const observer = new ResizeObserver(onResize);
  runtime.resizeobserver = observer;
  observer.observe(mount);
  const onVisible = () => {
    if (!document.hidden) onResize();
  };
  document.addEventListener('visibilitychange', onVisible);
  window.addEventListener('focus', onResize);
  return () => {
    observer.disconnect();
    document.removeEventListener('visibilitychange', onVisible);
    window.removeEventListener('focus', onResize);
  };
}
