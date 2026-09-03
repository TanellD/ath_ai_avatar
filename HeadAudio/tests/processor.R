# Get directory
get_script_dir <- function() {
  # Rscript
  cmdArgs <- commandArgs(trailingOnly = FALSE)
  fileArg <- "--file="
  scriptPath <- sub(fileArg, "", cmdArgs[grep(fileArg, cmdArgs)])
  if (length(scriptPath) > 0)
    return(dirname(normalizePath(scriptPath)))
  
  # RStudio
  if (requireNamespace("rstudioapi", quietly = TRUE) &&
      rstudioapi::isAvailable()) {
    p <- rstudioapi::getActiveDocumentContext()$path
    if (nzchar(p)) return(dirname(p))
  }
  
  # Fallback to working directory
  return(getwd())
}

# Read the CSV
scriptDir <- get_script_dir()
csvPath <- file.path(scriptDir, "processor.csv")
df <- read.csv(csvPath, header=FALSE)

# Values
values <- df$V1
cat("Samples:", length(values))

# 99.9th percentile
p999 <- quantile(values, probs = 0.999)
cat("Value below which 99.9% of data fall:", p999, "\n")

# Density plot
threshold <- 0.05
typical <- values[values <= threshold]
dens <- density(typical)
par(bg = "white")
plot(dens,
     xlim = c(0,threshold),
     main = "",
     xlab = "Milliseconds",
     ylab = "Frequency Density",  # <-- custom y label
     lwd = 2,
     bty = "n",
     col = "black")

# Find local maxima
y <- dens$y
x <- dens$x
peaks_idx <- which(diff(sign(diff(y))) == -2) + 1  # local maxima
peaks_x <- x[peaks_idx]
peaks_y <- y[peaks_idx]

# 3. Sort peaks by height (descending)
ord <- order(peaks_y, decreasing = TRUE)
peaks_x <- peaks_x[ord]
peaks_y <- peaks_y[ord]

# 4. Pick two peaks that are at least 0.01 apart
selected <- c(peaks_x[1])  # tallest peak
for(px in peaks_x[-1]){
  if(all(abs(px - selected) >= 0.01)){
    selected <- c(selected, px)
    if(length(selected) == 2) break
  }
}

# Get y values of the selected peaks
selected_y <- peaks_y[peaks_x %in% selected]

# Add points and custom labels
points(selected, selected_y, pch = 19, col = "red")
custom_labels <- c("Downsampling only", "MFCC +\nClassification")
text(selected, selected_y, labels = custom_labels, pos = 4, col = "red")

