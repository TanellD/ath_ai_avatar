# Install ggplot2 if needed
if(!require(ggplot2)) install.packages("ggplot2")
library(ggplot2)

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
csvPath <- file.path(scriptDir, "distances.csv")
df <- read.csv(csvPath, row.names = 1, check.names = FALSE)

# Drop the last row and column ("s1")
# Reverse the data
df <- df[-nrow(df), -ncol(df)]

# Convert matrix to long format
long_df <- data.frame(
  Var1 = rep(rownames(df), times = ncol(df)),
  Var2 = rep(colnames(df), each = nrow(df)),
  Distance = as.vector(as.matrix(df)),
  stringsAsFactors = FALSE
)

# ---------------------------
# IMPORTANT: preserve plotting order by making factors with explicit levels
# - For x (Var1) we want the rownames order (which after flip is the desired left->right order)
# - For y (Var2) we want the column order BUT because we've flipped df rows,
#   typical heatmap y-direction needs Var2 levels to be the reverse of their appearance
#   so that the visual row order matches the matrix row order.
# Adjust these lines if you want a different orientation.
# ---------------------------
long_df$Var1 <- factor(long_df$Var1, levels = rownames(df))            # left->right order preserved
long_df$Var2 <- factor(long_df$Var2, levels = rev(colnames(df)))       # top->bottom matches flipped rows


# Plot heatmap
ggplot(long_df, aes(x = Var1, y = Var2, fill = Distance)) +
  geom_tile() +
  geom_text(aes(label = round(Distance, 2)), size = 2.5) +   # adjust size if crowded
  scale_fill_gradient(low = "white", high = "red") +
  scale_x_discrete(position = "top") +                     # labels on top
  theme_minimal() +
  theme(
    axis.text.x = element_text(angle = 0, vjust = 0.5, hjust = 0.5, size = 10),
    axis.text.y = element_text(size = 10),
    axis.title = element_blank(),
    axis.ticks.length = unit(2, "pt"),
    panel.grid = element_blank()
  )
