/* Bus Topology diagram — the interactive part of the page.
 *
 * Loaded as a plain file by visualizer/components/topology_page.py and pasted
 * into the page, so this is ordinary JavaScript: no Python escaping, and your
 * editor can check it. Everything it needs arrives in one object that Python
 * writes just before this script runs:
 *
 *   window.SIGNALCRAFT_TOPOLOGY = {
 *     title, grouped, regions, nodes, edges, functionBorder,
 *     layout: { physG, physSpring, physK, physOverlap, physIters,
 *               postG, postSpring, postK, postOverlap }
 *   }
 *
 * Uses vis-network, which is read from the installed pyvis package — the app
 * never fetches anything from the internet.
 */
(function () {
  "use strict";
  const cfg = window.SIGNALCRAFT_TOPOLOGY;

      document.getElementById("title").textContent = cfg.title;
      const grouped = cfg.grouped;
      const regions = cfg.regions;
      const regionById = {};
      regions.forEach(function (r) { regionById[r.id] = r; });

      const nodes = new vis.DataSet(cfg.nodes);
      const edges = new vis.DataSet(cfg.edges);
      const container = document.getElementById("topo");
      let draggingId = null;
      let dragKind = null;
      let lastDragPos = null;
      let layoutDone = false;
      let savedView = null;

      function captureView() {
        return {
          scale: network.getScale(),
          position: network.getViewPosition()
        };
      }
      function restoreView(view) {
        if (!view) return;
        network.moveTo({
          scale: view.scale,
          position: view.position,
          animation: false
        });
      }
      function pinNode(id) {
        const n = nodes.get(id);
        if (!n) return;
        nodes.update({
          id: id,
          fixed: { x: true, y: true },
          borderWidth: n.kind === "lru" ? 1 : 3
        });
      }
      function unpinNode(id) {
        nodes.update({ id: id, fixed: { x: false, y: false } });
      }

      function syncRegionsFromFunctions() {
        nodes.forEach(function (n) {
          if (n.kind !== "function") return;
          const pos = network.getPositions([n.id])[n.id];
          if (!pos) return;
          const r = regionById[n.function_id];
          if (!r) return;
          r.x = pos.x;
          r.y = pos.y;
        });
      }

      function placeLrusInRegions() {
        regions.forEach(function (r) {
          const members = r.members || [];
          const cols = Math.max(1, Math.ceil(Math.sqrt(Math.max(members.length, 1))));
          const pad = r.pad || 40;
          members.forEach(function (mid, j) {
            const lc = j % cols;
            const lr = Math.floor(j / cols);
            const x = r.x - r.w / 2 + pad + 50 + lc * 85;
            const y = r.y - r.h / 2 + pad + 55 + lr * 55;
            nodes.update({
              id: mid,
              x: x,
              y: y,
              fixed: { x: true, y: true }
            });
          });
        });
      }

      function clampLruToRegion(n) {
        if (!n || n.kind !== "lru" || !n.function_id) return;
        const r = regionById[n.function_id];
        if (!r) return;
        const pos = network.getPositions([n.id])[n.id] || n;
        const pad = r.pad || 30;
        const minX = r.x - r.w / 2 + pad;
        const maxX = r.x + r.w / 2 - pad;
        const minY = r.y - r.h / 2 + pad + 24;
        const maxY = r.y + r.h / 2 - pad;
        const x = Math.min(maxX, Math.max(minX, pos.x));
        const y = Math.min(maxY, Math.max(minY, pos.y));
        nodes.update({ id: n.id, x: x, y: y });
      }

      const network = new vis.Network(
        container,
        { nodes, edges },
        {
          physics: {
            enabled: true,
            stabilization: {
              enabled: true,
              iterations: grouped ? 200 : cfg.layout.physIters,
              fit: true
            },
            barnesHut: {
              gravitationalConstant: grouped ? -12000 : cfg.layout.physG,
              springLength: grouped ? 200 : cfg.layout.physSpring,
              springConstant: grouped ? 0.02 : cfg.layout.physK,
              damping: 0.45,
              avoidOverlap: grouped ? 1 : cfg.layout.physOverlap
            }
          },
          interaction: {
            dragNodes: true,
            dragView: true,
            zoomView: true,
            hover: true,
            tooltipDelay: 120,
            hideEdgesOnDrag: false,
            multiselect: false
          },
          nodes: { font: { size: 12 }, borderWidth: 1 },
          edges: { smooth: { type: "continuous" }, selectionWidth: 1 }
        }
      );

      document.getElementById("btn-home").onclick = function () {
        network.fit({
          animation: { duration: 250, easingFunction: "easeInOutQuad" },
          padding: 30
        });
      };
      document.getElementById("btn-full").onclick = function () {
        const el = document.getElementById("wrap");
        if (!document.fullscreenElement) {
          if (el.requestFullscreen) el.requestFullscreen();
          else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
        } else if (document.exitFullscreen) {
          document.exitFullscreen();
        }
      };
      document.getElementById("btn-save").onclick = function () {
        const canvas = network.canvas && network.canvas.frame && network.canvas.frame.canvas;
        if (!canvas) return;
        const link = document.createElement("a");
        link.download = "bus_topology.png";
        link.href = canvas.toDataURL("image/png");
        link.click();
      };

      network.on("afterDrawing", function (ctx) {
        if (!grouped || !regions.length) return;
        regions.forEach(function (r) {
          const left = r.x - r.w / 2;
          const top = r.y - r.h / 2;
          ctx.save();
          ctx.strokeStyle = cfg.functionBorder;
          ctx.lineWidth = 2;
          ctx.setLineDash([6, 4]);
          ctx.strokeRect(left, top, r.w, r.h);
          ctx.setLineDash([]);
          ctx.fillStyle = "#333";
          ctx.font = "12px arial";
          ctx.fillText(r.label, left + 10, top + 16);
          ctx.restore();
        });
      });

      if (grouped) {
        network.on("stabilizationProgress", function () {
          syncRegionsFromFunctions();
          placeLrusInRegions();
        });
      }

      network.once("stabilizationIterationsDone", function () {
        if (grouped) {
          syncRegionsFromFunctions();
          placeLrusInRegions();
          layoutDone = true;
          nodes.forEach(function (n) {
            if (n.kind === "function" || n.kind === "bus" || n.kind === "lru") {
              pinNode(n.id);
            }
          });
          network.setOptions({ physics: { enabled: false } });
        } else {
          nodes.forEach(function (n) {
            if (n.kind === "bus") pinNode(n.id);
          });
          network.setOptions({
            physics: {
              enabled: true,
              stabilization: { enabled: true, fit: false },
              barnesHut: {
                gravitationalConstant: cfg.layout.postG,
                springLength: cfg.layout.postSpring,
                springConstant: cfg.layout.postK,
                damping: 0.55,
                avoidOverlap: cfg.layout.postOverlap
              }
            }
          });
        }
        // Initial fit only — later drags must not re-fit.
        network.fit({ animation: false, padding: 30 });
      });

      network.on("dragStart", function (params) {
        if (!params.nodes || params.nodes.length !== 1) return;
        const id = params.nodes[0];
        const n = nodes.get(id);
        if (!n) return;
        draggingId = id;
        dragKind = n.kind;
        savedView = captureView();
        const pos = network.getPositions([id])[id];
        lastDragPos = pos ? { x: pos.x, y: pos.y } : null;
        unpinNode(id);
      });

      network.on("dragging", function () {
        if (!grouped || dragKind !== "function" || !draggingId || !lastDragPos) return;
        const pos = network.getPositions([draggingId])[draggingId];
        if (!pos) return;
        const dx = pos.x - lastDragPos.x;
        const dy = pos.y - lastDragPos.y;
        lastDragPos = { x: pos.x, y: pos.y };
        const fnId = nodes.get(draggingId).function_id;
        const r = regionById[fnId];
        if (!r) return;
        r.x += dx;
        r.y += dy;
        const updates = [];
        (r.members || []).forEach(function (mid) {
          const p = network.getPositions([mid])[mid];
          if (!p) return;
          updates.push({
            id: mid,
            x: p.x + dx,
            y: p.y + dy,
            fixed: { x: true, y: true }
          });
        });
        if (updates.length) nodes.update(updates);
      });

      network.on("dragEnd", function () {
        if (!draggingId) return;
        const n = nodes.get(draggingId);
        const pos = network.getPositions([draggingId])[draggingId];
        if (pos) nodes.update({ id: draggingId, x: pos.x, y: pos.y });

        if (dragKind === "function" && n) {
          const r = regionById[n.function_id];
          if (r && pos) {
            r.x = pos.x;
            r.y = pos.y;
          }
          pinNode(draggingId);
          placeLrusInRegions();
          restoreView(savedView);
        } else if (dragKind === "lru" && grouped) {
          clampLruToRegion(nodes.get(draggingId));
          pinNode(draggingId);
          restoreView(savedView);
        } else if (dragKind === "bus") {
          pinNode(draggingId);
          if (!grouped) {
            const view = savedView || captureView();
            network.setOptions({
              physics: {
                enabled: true,
                stabilization: { enabled: true, fit: false, iterations: 40 }
              }
            });
            network.once("stabilized", function () {
              restoreView(view);
            });
            network.stabilize(40);
          } else {
            restoreView(savedView);
          }
        } else {
          pinNode(draggingId);
          restoreView(savedView);
        }
        draggingId = null;
        dragKind = null;
        lastDragPos = null;
        savedView = null;
      });
})();
