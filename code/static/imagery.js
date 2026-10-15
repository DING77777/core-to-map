"use strict";

(() => {
  const sources = {
    aerial: {
      source:"Landgate / SLIP",
      title:"Locate WA public aerial imagery",
      endpoint:"https://public-services.slip.wa.gov.au/public/services/SLIP_Public_Services/Locate/MapServer/WMSServer",
      index_endpoint:"https://public-services.slip.wa.gov.au/public/rest/services/SLIP_Public_Services/Locate/MapServer/0/query",
      layer:"1", crs:"EPSG:7844", max_size:2048,
      licence:"SLIP Transaction Personal Use Licence",
      licence_url:"https://www.landgate.wa.gov.au/siteassets/documents/location-data-and-services/licensing/slip-transaction-personal-use-licence-300523.pdf",
      source_url:"https://catalogue.data.wa.gov.au/dataset/locate-wa-mosaic",
      attribution:"© Western Australian Land Information Authority (Landgate) / SLIP",
      note:"Public online aerial imagery. Capture date, resolution and positional accuracy vary by location. Display background only; it does not change drillhole queries."
    }
  };
  const views = new Map();
  let mode = "aerial";
  let lastMode = mode;

  function dispose(view) {
    clearTimeout(view.timer);
    view.controller?.abort();
    view.detailController?.abort();
    if (view.href) URL.revokeObjectURL(view.href);
  }

  function setMode(value) {
    if (!["aerial", "map"].includes(value)) return;
    if (mode === value) return;
    mode = value;
    if (mode !== "map") lastMode = mode;
    views.forEach(dispose);
    views.clear();
  }

  function setEnabled(value) {
    setMode(value ? lastMode : "map");
  }

  function active(key, view) {
    return mode === view.mode && views.get(key) === view;
  }

  function changed(key, view) {
    queueMicrotask(() => {
      if (active(key, view)) view.onChange?.();
    });
  }

  function result(view) {
    return {href:view.href, status:view.status, message:view.message, mode:view.mode,
      crs:sources[view.mode]?.crs, detail:view.detail};
  }

  function boundsError(bounds) {
    if (!bounds || !["west", "south", "east", "north", "width", "height"].every((name) => Number.isFinite(bounds[name]))) {
      return "Imagery needs a valid map extent.";
    }
    if (bounds.west >= bounds.east || bounds.south >= bounds.north) {
      return "Imagery needs a non-empty map extent.";
    }
    if (bounds.west < -180 || bounds.east > 180 || bounds.south < -90 || bounds.north > 90) {
      return "Imagery needs valid longitude and latitude bounds.";
    }
    const extent = {west:96.79, south:-35.32, east:129.82, north:-10.40};
    if (bounds.east <= extent.west || bounds.west >= extent.east || bounds.north <= extent.south || bounds.south >= extent.north) {
      return "Landgate imagery covers Western Australia. Move the map back to WA.";
    }
    if (bounds.width < 1 || bounds.height < 1 || bounds.width > 4096 || bounds.height > 4096) {
      return "Imagery needs a map size between 1 and 4096 pixels.";
    }
    return "";
  }

  function imageURL(bounds, source) {
    const url = new URL(source.endpoint);
    const scale = Math.min(1, source.max_size / bounds.width, source.max_size / bounds.height);
    const params = {
      SERVICE:"WMS", VERSION:"1.3.0", REQUEST:"GetMap",
      LAYERS:source.layer, STYLES:"default",
      CRS:source.crs, BBOX:[bounds.south, bounds.west, bounds.north, bounds.east].join(","),
      WIDTH:String(Math.max(1, Math.round(bounds.width * scale))),
      HEIGHT:String(Math.max(1, Math.round(bounds.height * scale))),
      FORMAT:"image/png", TRANSPARENT:"TRUE"
    };
    url.search = new URLSearchParams(params).toString();
    return url.href;
  }

  async function hasVisiblePixels(blob) {
    const bitmap = await createImageBitmap(blob);
    try {
      const canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const context = canvas.getContext("2d", {willReadFrequently:true});
      context.drawImage(bitmap, 0, 0);
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
      for (let offset = 3; offset < pixels.length; offset += 4) {
        if (pixels[offset] > 0) return true;
      }
      return false;
    } finally {
      bitmap.close();
    }
  }

  function positiveNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) && number > 0 ? number : null;
  }

  async function loadDetail(key, view, bounds) {
    const controller = new AbortController();
    view.detailController = controller;
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const url = new URL(sources.aerial.index_endpoint);
      url.search = new URLSearchParams({
        f:"json", geometry:JSON.stringify({x:(bounds.west + bounds.east) / 2, y:(bounds.south + bounds.north) / 2}),
        geometryType:"esriGeometryPoint", inSR:"7844", spatialRel:"esriSpatialRelIntersects",
        outFields:"name,ground_resolution,capture_date_text,accuracy_in_meters",
        returnGeometry:"false", resultRecordCount:"5"
      }).toString();
      const response = await fetch(url.href, {signal:controller.signal, credentials:"omit", referrerPolicy:"no-referrer"});
      if (!response.ok) return;
      const data = await response.json();
      if (!active(key, view) || data.error || !Array.isArray(data.features) || !data.features.length) return;
      const samples = data.features.map(({attributes}) => ({
        name:String(attributes?.name || "").slice(0, 160),
        resolution_m:positiveNumber(attributes?.ground_resolution),
        capture_date:String(attributes?.capture_date_text || "").slice(0, 160),
        accuracy_m:positiveNumber(attributes?.accuracy_in_meters)
      }));
      view.detail = {samples, note:"Index at the map centre; coverage can vary across the view."};
      if (samples.length === 1) {
        const sample = samples[0];
        view.message = "Landgate Locate" + (sample.resolution_m ? " · " + sample.resolution_m + " m at map centre" : "")
          + (sample.capture_date ? " · captured " + sample.capture_date : "");
      }
      changed(key, view);
    } catch {
      // Index availability does not determine whether the image can be displayed.
    } finally {
      clearTimeout(timeout);
      view.detailController = null;
    }
  }

  async function request(key, view, bounds) {
    if (!active(key, view)) return;
    const source = sources[view.mode];
    const controller = new AbortController();
    view.controller = controller;
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(imageURL(bounds, source), {signal:controller.signal, credentials:"omit", referrerPolicy:"no-referrer"});
      if (!response.ok) throw new Error("Imagery service returned HTTP " + response.status + ".");
      if (!/^image\//i.test(response.headers.get("content-type") || "")) {
        throw new Error("Imagery service did not return an image.");
      }
      const blob = await response.blob();
      if (!blob.size) throw new Error("Imagery service returned an empty image.");
      if (!await hasVisiblePixels(blob)) {
        const error = new Error("No imagery pixels returned for this extent.");
        error.name = "NoCoverageError";
        throw error;
      }
      if (!active(key, view)) return;
      view.href = URL.createObjectURL(blob);
      view.status = "ready";
      view.message = "Landgate Locate · online aerial imagery · GDA2020";
    } catch (error) {
      if (!active(key, view)) return;
      view.status = "error";
      view.message = error.name === "AbortError"
        ? "Imagery timed out. Switch the background to retry."
        : error.name === "NoCoverageError"
        ? "No imagery pixels at this scale or extent."
        : "Imagery unavailable. Switch the background to retry.";
    } finally {
      clearTimeout(timeout);
      view.controller = null;
    }
    if (active(key, view)) {
      changed(key, view);
      if (key === "local" && view.mode === "aerial" && view.status === "ready") loadDetail(key, view, bounds);
    }
  }

  function view(key, bounds, onChange) {
    if (mode === "map") return {href:null, status:"off", message:"Online imagery is off.", mode, detail:null};
    const signature = JSON.stringify(bounds && [mode, bounds.west, bounds.south, bounds.east, bounds.north, bounds.width, bounds.height]);
    const previous = views.get(key);
    if (previous?.signature === signature) {
      previous.onChange = onChange;
      return result(previous);
    }
    if (previous) dispose(previous);
    const error = boundsError(bounds);
    const current = {signature, mode, href:null, detail:null, status:error ? "error" : "loading",
      message:error || "Loading online imagery…", onChange, timer:null, controller:null, detailController:null};
    views.set(key, current);
    if (!error) current.timer = setTimeout(() => request(key, current, {...bounds}), 300);
    return result(current);
  }

  function metadata() {
    const selected = sources[mode === "map" ? lastMode : mode];
    return {...selected, mode, online:true, opt_in:false, enabled:mode !== "map",
      local_context:mode === "aerial" ? views.get("local")?.detail || null : null};
  }

  window.HyLoggerImagery = {setEnabled, setMode, view, metadata};
})();
