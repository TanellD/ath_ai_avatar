import assert from 'node:assert/strict';
import { test } from 'node:test';
import { Quaternion, Vector3 } from 'three';
import { TalkingHead } from '@met4citizen/talkinghead';
import { stabilizeNonHumanoidPose, guardAvatarResize } from '../src/avatar/runtimeGuards.ts';

test('native pose survives repeated mood queues, long pauses and human balancing', () => {
  const hips = new Vector3(0.1, 0.8, -0.2);
  const rotation = new Quaternion();
  const runtime = {
    poseBase: { props: { 'Hips.position': hips.clone(), 'Head.quaternion': rotation.clone() } },
    poseAvatar: { props: { 'Hips.position': hips.clone(), 'Head.quaternion': rotation.clone() } },
    poseDelta: { props: { 'Hips.position': { x: 1, y: 2, z: 3 }, 'Head.quaternion': { x: 0, y: 0.2, z: 0 } } },
    updatePoseDelta: TalkingHead.prototype.updatePoseDelta,
    setPoseFromTemplate: TalkingHead.prototype.setPoseFromTemplate,
    mtAvatar: {},
    animQueue: [],
    animMoods: Object.fromEntries(['neutral', 'happy', 'sad', 'angry'].map(name => [name, {
      anims: [{ name: 'pose', vs: { pose: ['side'] } }],
    }])),
    animFactory: template => ({ template }),
  };
  const restoreRoot = stabilizeNonHumanoidPose(runtime);
  for (let frame = 0; frame < 1000; frame++) {
    TalkingHead.prototype.setMood.call(runtime, ['neutral', 'happy', 'sad', 'angry'][frame % 4]);
    assert.equal(runtime.animQueue.length, 1);
    runtime.setPoseFromTemplate(runtime.animQueue[0].template);
    runtime.updatePoseBase(frame * 60_000);
    runtime.updatePoseDelta();
    assert.ok(runtime.poseAvatar.props['Hips.position'].equals(hips));
    assert.ok(!runtime.poseAvatar.props['Head.quaternion'].equals(rotation), 'head gaze still moves');
    runtime.poseAvatar.props['Hips.position'].add(new Vector3(10, -20, 30));
    restoreRoot();
    assert.ok(runtime.poseAvatar.props['Hips.position'].equals(hips));
    assert.ok(runtime.poseBase.props['Hips.position'].equals(hips));
  }
});

test('resize skips zero dimensions, handles visibility/focus, and cleans up', () => {
  const originals = { ResizeObserver: globalThis.ResizeObserver, document: globalThis.document, window: globalThis.window };
  let observer;
  class Observer {
    constructor(callback) { this.callback = callback; observer = this; }
    observe() {}
    disconnect() { this.disconnected = true; }
  }
  globalThis.ResizeObserver = Observer;
  globalThis.document = new EventTarget();
  globalThis.window = new EventTarget();
  try {
    let calls = 0;
    const mount = { clientWidth: 800, clientHeight: 600 };
    const oldObserver = new Observer(() => {});
    const runtime = { resizeobserver: oldObserver, onResize() {
      assert.ok(Number.isFinite(mount.clientWidth / mount.clientHeight));
      calls++;
    } };
    const dispose = guardAvatarResize(runtime, mount);
    assert.ok(oldObserver.disconnected);
    for (const [width, height] of [[0, 0], [800, 0], [0, 600]]) {
      mount.clientWidth = width; mount.clientHeight = height;
      observer.callback();
      window.dispatchEvent(new Event('focus'));
    }
    assert.equal(calls, 0);
    mount.clientWidth = 800; mount.clientHeight = 600;
    observer.callback();
    document.hidden = true;
    document.dispatchEvent(new Event('visibilitychange'));
    assert.equal(calls, 1);
    document.hidden = false;
    document.dispatchEvent(new Event('visibilitychange'));
    window.dispatchEvent(new Event('focus'));
    assert.equal(calls, 3);
    dispose();
    assert.ok(observer.disconnected);
    document.dispatchEvent(new Event('visibilitychange'));
    window.dispatchEvent(new Event('focus'));
    assert.equal(calls, 3);
  } finally {
    for (const [key, value] of Object.entries(originals)) {
      if (value === undefined) delete globalThis[key];
      else globalThis[key] = value;
    }
  }
});
